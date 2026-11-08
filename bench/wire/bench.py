"""Should state messages be binary? The wire benchmark.

Compares four ways of sending the 30-a-second state messages:

    json+deflate   today: JSON (delta.py), compressed per connection
                   (permessage-deflate, as aiohttp does it)
    json           JSON, not compressed
    bin            the prototype binary format (bench/wire/proto.py), not compressed
    bin+deflate    binary, compressed

    python -m bench.wire.bench check      # the prototype gives exactly the same states (Python and JS)
    python -m bench.wire.bench micro      # server CPU per stage, per room per tick
    python -m bench.wire.bench sockets    # a real server, real WebSockets: CPU at a fixed load
    python -m bench.wire.bench capacity   # ... and how many rooms one core keeps up with
    python -m bench.wire.bench all

Each writes its numbers to bench/wire/results/<name>.json and prints a
table. tests/web/wire_bench.js times the phone side (decoding) in Chromium.

How it stays honest:
- The states are from real matches (bots playing, several maps, modes and
  player counts), recorded once and replayed to every variant.
- Variants take turns within each round (in a shuffled order), so a slow
  patch of the machine hits all of them; results are medians over rounds
  with 95% bootstrap intervals, and differences are paired by round.
- The socket tests run the real server (game, rooms, aiohttp) on one
  pinned core, with the browsers in other processes on other cores,
  and check every browser actually got its 30 states a second.
"""
import argparse
import base64
import gc
import json
import os
import random
import statistics
import subprocess
import sys
import time
import zlib

from bonk_game.server import delta
from bonk_game.server.match import Match
from bench.wire import proto

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
VARIANTS = ("json+deflate", "json", "bin", "bin+deflate")

# (map, players, mode, power-ups): a spread of what's played
SCENARIOS = (
    ("classic", 2, "ffa", False),
    ("classic", 4, "ffa", False),
    ("platform", 4, "knockouts", True),
    ("ramps", 6, "crown", True),
    ("grand", 8, "ffa", True),
    ("decks", 10, "lives", True),
)

WS_TRAILER = b"\x00\x00\xff\xff"
# Per message on the wire besides the WebSocket payload, for one message a
# packet (aiohttp sets TCP_NODELAY): TLS 1.3 record 22, TCP 32 (with
# timestamps), IPv4 20 (IPv6: 40). The WebSocket frame header is added per
# message from its length.
TLS_TCP_IP = 22 + 32 + 20


def ws_header(n):
    return 2 if n < 126 else 4 if n < 65536 else 10


def scenario_name(sc):
    m, n, mode, pu = sc
    return f"{m} {n}p {mode}{' +power-ups' if pu else ''}"


# --- recording -------------------------------------------------------------

def record(sc, ticks, seed=1, warmup=150):
    """Play a match with bots; returns a list of (full state, message,
    motions) for `ticks` ticks from the first keyframe after `warmup`, and the average cost of the
    game itself (tick + snapshot + delta) per tick, in seconds."""
    map_name, n, mode, pu = sc
    m = Match(map_name, [{"kind": "bot:hard", "name": f"b{i}"} for i in range(n)], 1000,
              mode=mode, power_ups=pu, seed=seed)
    enc = delta.Encoder()
    out, game = [], 0.0
    t = 0
    while len(out) < ticks:
        t0 = time.perf_counter()
        events = m.tick()
        s = m.snapshot()
        s["events"] = events
        msg = enc.encode(s)
        motions = [m.motion(k) for k in range(n)]
        dt = time.perf_counter() - t0
        t += 1
        # (from a keyframe on, so the messages can be rebuilt from the start)
        if out or (t > warmup and msg["type"] == "state"):
            game += dt
            out.append((json.loads(json.dumps(s)), msg, motions))
        if m.finished:
            raise RuntimeError(f"{scenario_name(sc)}: the match finished early")
    return out, game / max(1, len(out))


def people_cost(sc, ticks, seed=1, warmup=150):
    """What the game costs per tick when people play every ball (pressing
    random buttons every 0.1-0.5 s, as load_test.py's people do) instead of
    bots, which cost CPU people don't. Seconds per tick."""
    map_name, n, mode, pu = sc
    m = Match(map_name, [{"kind": "human", "name": f"p{i}"} for i in range(n)], 1000,
              mode=mode, power_ups=pu, seed=seed)
    rng = random.Random(seed)
    enc = delta.Encoder()
    nxt = [0] * n
    took = 0.0
    for t in range(warmup + ticks):
        for k in range(n):
            if t >= nxt[k]:
                m.set_input(k, [int(rng.random() < q) for q in (0.15, 0.4, 0.1, 0.4, 0.3)])
                nxt[k] = t + rng.randint(3, 15)
        t0 = time.perf_counter()
        events = m.tick()
        s = m.snapshot()
        s["events"] = events
        enc.encode(s)
        if t >= warmup:
            took += time.perf_counter() - t0
    return took / ticks


# --- the four ways to send one tick ---------------------------------------

def make_sender(variant, n):
    """A function(msg, motions) -> list of the n payloads one tick sends
    (bytes, as they'd go into WebSocket frames), with its own per-connection
    compressors, as each connection has."""
    deflate = variant.endswith("+deflate")
    comps = [zlib.compressobj(1, zlib.DEFLATED, -15) for _ in range(n)] if deflate else None
    sync = zlib.Z_SYNC_FLUSH

    if variant.startswith("json"):
        def payloads(msg, motions):
            text = json.dumps(msg, separators=(",", ":"))
            head = text[:-1]
            out = [f'{head},"you":[{vx},{vy},{g}]}}'.encode() for vx, vy, g in motions]
            return out
    else:
        def payloads(msg, motions):
            body = proto.encode(msg)
            return [body + proto.you(mo) for mo in motions]

    if not deflate:
        return payloads

    def compressed(msg, motions):
        return [(c.compress(p) + c.flush(sync)).removesuffix(WS_TRAILER)
                for c, p in zip(comps, payloads(msg, motions))]
    return compressed


# --- check: the prototype means exactly the same --------------------------

def check(ticks=900):
    os.makedirs(RESULTS, exist_ok=True)
    fixtures = os.path.join(RESULTS, "fixtures.jsonl")
    total = clamped = 0
    with open(fixtures, "w") as f:
        for sc in SCENARIOS:
            rec, _ = record(sc, ticks)
            prev = None
            for full, msg, motions in rec:
                mo = motions[0]
                body = proto.encode(msg) + proto.you(mo)
                got, c = proto.decode(body)
                clamped += c
                want = {**msg, "you": list(mo)}
                if got != want and not c:
                    raise AssertionError(f"{scenario_name(sc)} tick {msg['tick']}: {got} != {want}")
                # And the states rebuilt from the decoded messages are the same
                got.pop("you")
                state = got if got["type"] == "state" else delta.apply(prev, got)
                want_state = {**full, "type": "state"}
                if not c and {k: v for k, v in state.items() if k != "events"} != \
                        {k: v for k, v in want_state.items() if k != "events"}:
                    raise AssertionError(f"{scenario_name(sc)} tick {msg['tick']}: rebuilt state differs")
                prev = state
                total += 1
                f.write(json.dumps({"scenario": scenario_name(sc), "json": json.dumps(want, separators=(",", ":")),
                                    "bin": base64.b64encode(body).decode()}) + "\n")
    print(f"Python: {total} messages from {len(SCENARIOS)} scenarios decode to exactly the same message"
          f" and rebuild exactly the same states ({clamped} numbers clamped)")
    fuzz()
    r = subprocess.run(["node", os.path.join(HERE, "check.js"), fixtures], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode:
        raise SystemExit("the JS decoder disagrees")


def fuzz(n=20000, seed=3):
    """Random messages (any mix of fields, any values in range) round-trip;
    a ball past the range is clamped and counted, not wrapped around."""
    rng = random.Random(seed)
    r1 = lambda lo, hi: round(rng.uniform(lo, hi), 1)
    for _ in range(n):
        k = rng.randint(0, 10)
        balls = {str(i): [r1(-3276, 3276), r1(-3276, 3276), round(rng.random(), 2), rng.randint(0, 1)]
                 for i in rng.sample(range(10), k)}
        msg = {"type": rng.choice(("state", "d")), "tick": rng.randint(0, 2 ** 32 - 1)}
        if rng.random() < 0.8:
            msg["t"] = round(rng.uniform(0, 40000), 2)
        if rng.random() < 0.5:
            msg["timer"] = rng.choice((None, r1(0, 999)))
        if rng.random() < 0.9:
            msg["players"] = list(balls.values()) if msg["type"] == "state" else balls
        if rng.random() < 0.3:
            msg["events"] = [{"kind": "hit", "x": 1.5, "s": "ü"}]
        if rng.random() < 0.2:
            msg["gone"] = ["held"]
        mo = [r1(-3000, 3000), r1(-3000, 3000), rng.randint(0, 1)]
        for body, want in ((proto.encode(msg), msg), (proto.encode(msg) + proto.you(mo), {**msg, "you": mo})):
            got, c = proto.decode(body)
            assert c == 0 and got == want, (got, want)
    far, c = proto.decode(proto.encode({"type": "d", "tick": 1, "players": {"0": [5000.0, -9000.0, 0.5, 1]}}))
    assert c == 2 and far["players"]["0"][:2] == [3276.7, -3276.7], far
    print(f"Python: {n} random messages round-trip exactly; a ball far off the map is clamped, not wrapped")


# --- micro: server CPU per stage ------------------------------------------

def _boot_ci(xs, stat=statistics.median, k=2000, seed=0):
    rng = random.Random(seed)
    vals = sorted(stat([rng.choice(xs) for _ in xs]) for _ in range(k))
    return vals[int(k * 0.025)], vals[int(k * 0.975)]


def micro(ticks=900, rounds=15, seed=0):
    rng = random.Random(seed)
    results = []
    for sc in SCENARIOS:
        rec, game = record(sc, ticks)
        msgs = [(m, mo) for _, m, mo in rec]
        n = sc[1]
        times = {v: [] for v in VARIANTS}
        sizes = {}
        for r in range(rounds + 1):  # (round 0 warms up, not counted)
            order = list(VARIANTS)
            rng.shuffle(order)
            for v in order:
                send = make_sender(v, n)
                gc.collect()
                nbytes = wire = 0
                t0 = time.perf_counter()
                for m, mo in msgs:
                    out = send(m, mo)
                    if r == 0:
                        for p in out:
                            nbytes += len(p)
                            wire += len(p) + ws_header(len(p)) + TLS_TCP_IP
                dt = time.perf_counter() - t0
                if r == 0:
                    sizes[v] = (nbytes / len(msgs) / n, wire / len(msgs) / n)
                else:
                    times[v].append(dt / len(msgs) * 1e6)  # us per room per tick
        row = {"scenario": scenario_name(sc), "players": n, "game_us": game * 1e6,
               "game_people_us": people_cost(sc, ticks) * 1e6, "variants": {}}
        base = times["json+deflate"]
        for v in VARIANTS:
            med = statistics.median(times[v])
            diffs = [a - b for a, b in zip(times[v], base)]
            row["variants"][v] = {
                "us": med, "ci": _boot_ci(times[v]),
                "vs_today_us": statistics.median(diffs), "vs_today_ci": _boot_ci(diffs),
                "payload_b": sizes[v][0], "wire_b": sizes[v][1],
            }
        results.append(row)
        print(f"{row['scenario']}: done", file=sys.stderr, flush=True)
    _save("micro", {"ticks": ticks, "rounds": rounds, "rows": results})
    print_micro(results, rounds)
    return results


def print_micro(rows, rounds):
    print(f"\nServer CPU to send one tick to everyone in a room (median of {rounds} rounds, 95% interval),"
          " and what the game itself costs per tick:\n")
    print("| scenario | game, bots playing | game, people playing | " + " | ".join(VARIANTS) + " |")
    print("|---|---|---|" + "---|" * len(VARIANTS))
    for r in rows:
        cells = []
        for v in VARIANTS:
            x = r["variants"][v]
            cells.append(f"{x['us']:.0f} µs ({x['ci'][0]:.0f}–{x['ci'][1]:.0f})")
        print(f"| {r['scenario']} | {r['game_us']:.0f} µs | {r['game_people_us']:.0f} µs | " + " | ".join(cells) + " |")
    print("\nSending as a share of all the server's work for a room (game with people playing + sending):\n")
    print("| scenario | " + " | ".join(VARIANTS) + " |")
    print("|---|" + "---|" * len(VARIANTS))
    for r in rows:
        print(f"| {r['scenario']} | " + " | ".join(
            f"{100 * r['variants'][v]['us'] / (r['game_people_us'] + r['variants'][v]['us']):.0f}%" for v in VARIANTS) + " |")
    print("\nBytes per player per message: payload / on the wire (with WebSocket, TLS, TCP and IP headers):\n")
    print("| scenario | " + " | ".join(VARIANTS) + " |")
    print("|---|" + "---|" * len(VARIANTS))
    for r in rows:
        print(f"| {r['scenario']} | " + " | ".join(
            f"{r['variants'][v]['payload_b']:.0f} / {r['variants'][v]['wire_b']:.0f} B" for v in VARIANTS) + " |")


def _save(name, data):
    os.makedirs(RESULTS, exist_ok=True)
    meta = {"python": sys.version.split()[0], "cpus": os.cpu_count(), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(RESULTS, f"{name}.json"), "w") as f:
        json.dump({"meta": meta, **data}, f, indent=1)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("what", choices=("check", "micro", "sockets", "capacity", "all"))
    p.add_argument("--ticks", type=int, default=900)
    p.add_argument("--rounds", type=int, default=15)
    a = p.parse_args(argv)
    if a.what in ("check", "all"):
        check(a.ticks)
    if a.what in ("micro", "all"):
        micro(a.ticks, a.rounds)
    if a.what in ("sockets", "capacity", "all"):
        from bench.wire import sockets
        if a.what in ("sockets", "all"):
            sockets.fixed()
        if a.what in ("capacity", "all"):
            sockets.capacity()


if __name__ == "__main__":
    main()
