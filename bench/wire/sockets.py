"""The wire benchmark with a real server and real WebSockets (see bench.py).

Each run is its own server process, pinned to one core (taskset), running
N rooms of people: the real game, rooms and aiohttp, with only the state
messages' format changed (patched in here, for "bin"). The browsers are
other processes on the other cores; they connect as browsers do (asking
for compression), play (random buttons, a ping a second) and check what
they get:
  - every browser's states are counted, so a variant can't look cheap by
    sending less (each must deliver 30 a second to everyone);
  - one browser per room decodes every state and rebuilds the match from
    them (delta.py), and any that doesn't rebuild is counted.

    python -m bench.wire.sockets fixed [--repeats 5] [--seconds 15]
    python -m bench.wire.sockets capacity [--repeats 2]
"""
import argparse
import asyncio
import json
import os
import random
import resource
import signal
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = ("json+deflate", "json", "bin", "bin+deflate")
SERVER_CORE = "0"
BROWSER_CORES = ("1", "2", "3")


def _cpu():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


# --- the server side (one process per run) --------------------------------

def patch_for(variant):
    """Make the real server send `variant`."""
    from bonk_game.server import limits, room as room_mod, web
    from bench.wire import proto
    limits.WS_COMPRESS = variant.endswith("+deflate")
    limits.CONNECTIONS_PER_IP = 10 ** 6
    limits.MAX_ROOMS = 10 ** 6
    if not variant.startswith("bin"):
        return
    real = json

    class BinJSON:
        """room.py's json, except states (and keyframes) come out as bytes."""
        loads = staticmethod(real.loads)

        @staticmethod
        def dumps(obj, **kw):
            if isinstance(obj, dict) and obj.get("type") in ("state", "d") and "tick" in obj:
                return proto.encode(obj)
            return real.dumps(obj, **kw)
    room_mod.json = BinJSON

    async def send_state(self, body, match):
        live = self.connected
        if not live:
            return
        slot = {t: k for k, t in enumerate(self.match_tokens) if t is not None}

        def for_member(m):
            k = slot.get(m.token)
            return body if k is None else body + proto.you(match.motion(k))
        await asyncio.gather(*(m.send(for_member(m)) for m in live), return_exceptions=True)
    room_mod.Room.send_state = send_state

    def _sender(ws):
        async def send(msg):
            if ws.closed:
                return
            if isinstance(msg, bytes):
                data, binary = msg, True
            else:
                data, binary = (msg if isinstance(msg, str) else real.dumps(msg, separators=(",", ":"))), False
            try:
                await (ws.send_bytes(data) if binary else ws.send_str(data))
                web.metrics.STATS.sent(len(data))
            except (ConnectionResetError, RuntimeError):
                pass
        return send
    web._sender = _sender


async def run_server(variant, n_rooms, people, map_name, seconds, seed=0):
    patch_for(variant)
    from bonk_game.server import load_test, metrics
    from bonk_game.server.room import RoomManager
    metrics.STATS = metrics.Stats()
    rooms = RoomManager(rng=random.Random(seed))
    made = [rooms.create() for _ in range(n_rooms)]
    runner, url = await load_test.serve(rooms)
    codes = [r.code for r in made]
    out_dir = tempfile.mkdtemp(prefix="wirebench-")
    groups = [codes[i::len(BROWSER_CORES)] for i in range(len(BROWSER_CORES))]
    browsers = [subprocess.Popen(["taskset", "-c", core, sys.executable, "-m", "bench.wire.sockets", "browsers",
                                  url, variant, str(people), os.path.join(out_dir, f"b{k}.json"), *g],
                                 env={**os.environ, "PYTHONPATH": os.getcwd()})
                for k, (core, g) in enumerate(zip(BROWSER_CORES, groups)) if g]
    try:
        end = time.monotonic() + 180
        while any(len(r.connected) < people for r in made):
            if time.monotonic() > end or any(b.poll() is not None for b in browsers):
                raise RuntimeError("the browsers didn't all connect")
            await asyncio.sleep(0.1)
        for room in made:
            room.settings.update(map=map_name, first_to=1000, bots=[])
            await room.start()
        await asyncio.sleep(3.0)  # (the countdown, everything settling)
        stats = metrics.STATS
        ticks0, late0 = stats.ticks_total, stats.late_ticks
        wire0, bytes0 = stats.wire_bytes, stats.bytes_sent
        stats.ticks.clear()
        loop = asyncio.get_running_loop()
        lag, stop = [], asyncio.Event()

        async def watch_lag():
            while not stop.is_set():
                want = loop.time() + 0.05
                await asyncio.sleep(0.05)
                lag.append(loop.time() - want)
        watcher = asyncio.ensure_future(watch_lag())
        w0, c0 = time.time(), _cpu()
        await asyncio.sleep(seconds)
        w1, c1 = time.time(), _cpu()
        stop.set()
        await watcher
        avg, p99 = stats.tick_ms()
        result = {
            "variant": variant, "rooms": n_rooms, "people": people, "map": map_name,
            "cpu_pct": 100 * (c1 - c0) / (w1 - w0),
            "tick_ms_avg": avg, "tick_ms_p99": p99,
            "ticks_per_s": (stats.ticks_total - ticks0) / (w1 - w0) / n_rooms,
            "late": stats.late_ticks - late0,
            "loop_lag_ms_p99": 1000 * sorted(lag)[int(len(lag) * 0.99)],
            "wire_kbit_per_player": (stats.wire_bytes - wire0) * 8 / 1000 / (w1 - w0) / (n_rooms * people),
            "payload_kbit_per_player": (stats.bytes_sent - bytes0) * 8 / 1000 / (w1 - w0) / (n_rooms * people),
        }
    finally:
        for b in browsers:
            b.send_signal(signal.SIGTERM)
        for b in browsers:
            try:
                b.wait(30)
            except subprocess.TimeoutExpired:
                b.kill()
        for room in rooms.rooms.values():
            await room.stop()
        await runner.cleanup()
    # What the browsers got, in the measured window
    rates, gaps, checked, bad, bcpu, kinds = [], [], 0, 0, [], set()
    for b in range(len(browsers)):
        with open(os.path.join(out_dir, f"b{b}.json")) as f:
            got = json.load(f)
        bcpu.append(got["cpu_pct"])
        checked += got["checked"]
        bad += got["bad"]
        kinds.update(got["kinds"])
        for times in got["arrivals"]:
            inside = [t for t in times if w0 <= t <= w1]
            rates.append(len(inside) / (w1 - w0))
            gaps += [b - a for a, b in zip(inside, inside[1:])]
    gaps.sort()
    result.update({
        "states_per_s_min": min(rates), "states_per_s_med": statistics.median(rates),
        "gap_ms_p99": 1000 * gaps[int(len(gaps) * 0.99)] if gaps else None,
        "checked": checked, "rebuild_failures": bad, "frame_kinds": sorted(kinds),
        "browser_cpu_pct_max": max(bcpu),
    })
    return result


# --- the browsers ---------------------------------------------------------

async def browsers(url, variant, people, out_path, codes):
    import aiohttp
    from bonk_game.server import delta
    from bonk_game.server.web import VERSION
    from bench.wire import proto
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    arrivals, kinds = [], set()
    tally = {"checked": 0, "bad": 0}
    gate = asyncio.Semaphore(20)
    c0, w0 = _cpu(), time.monotonic()

    async def one(session, code, k):
        times = []
        arrivals.append(times)
        rng = random.Random(f"{code}-{k}")
        for attempt in range(30):
            try:
                async with gate:
                    ws = await session.ws_connect(f"{url}/ws/{code}", max_msg_size=0, compress=15)
                break
            except aiohttp.ClientError:
                await asyncio.sleep(0.2 * (attempt + 1))
        else:
            raise RuntimeError(f"couldn't connect to {code}")
        checker = k == 0  # one browser a room rebuilds the match from what it gets
        state = None

        async def play():
            next_ping = time.monotonic() + rng.random()
            while not ws.closed:
                await ws.send_json({"type": "input", "b": [int(rng.random() < q) for q in (0.15, 0.4, 0.1, 0.4, 0.3)]})
                if time.monotonic() > next_ping:
                    await ws.send_json({"type": "ping", "t": time.time(), "rtt": 1})
                    next_ping += 1
                await asyncio.sleep(rng.uniform(0.1, 0.5))
        async with ws:
            await ws.send_json({"type": "hello", "name": f"P{k}", "token": f"{code}-{k}", "version": VERSION})
            player = asyncio.ensure_future(play())
            try:
                async for raw in ws:
                    if raw.type == aiohttp.WSMsgType.BINARY:
                        kinds.add(f"binary{'+deflate' if ws.compress else ''}")
                        times.append(time.time())
                        if checker:
                            msg, _ = proto.decode(raw.data)
                    elif raw.type == aiohttp.WSMsgType.TEXT:
                        d = raw.data
                        if d.startswith('{"type":"d"') or d.startswith('{"type":"state"'):
                            kinds.add(f"text{'+deflate' if ws.compress else ''}")
                            times.append(time.time())
                            if not checker:
                                continue
                            msg = json.loads(d)
                        else:
                            continue
                    else:
                        continue
                    if checker:
                        msg.pop("you", None)
                        if state is None and msg["type"] != "state":
                            continue  # (joined mid-match: waits for a keyframe, as the browser does)
                        try:
                            state = msg if msg["type"] == "state" else delta.apply(state, msg)
                            tally["checked"] += 1
                        except (ValueError, TypeError, KeyError):
                            state = None  # (waits for the next keyframe, as the browser does)
                            tally["bad"] += 1
            finally:
                player.cancel()

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as session:
        tasks = [asyncio.ensure_future(one(session, c, k)) for c in codes for k in range(people)]
        await stop.wait()
        cpu = 100 * (_cpu() - c0) / (time.monotonic() - w0)
        for t in tasks:
            t.cancel()
    with open(out_path, "w") as f:
        json.dump({"arrivals": arrivals, "kinds": sorted(kinds), "cpu_pct": cpu, **tally}, f)


# --- orchestration --------------------------------------------------------

def one_run(variant, rooms, people, map_name, seconds):
    r = subprocess.run(["taskset", "-c", SERVER_CORE, sys.executable, "-m", "bench.wire.sockets", "server",
                        variant, str(rooms), str(people), map_name, str(seconds)],
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": os.getcwd()})
    lines = [line for line in r.stdout.splitlines() if line.startswith("{")]
    if r.returncode or not lines:
        raise RuntimeError(f"{variant} {rooms} rooms failed:\n{r.stderr[-3000:]}")
    return json.loads(lines[-1])


def keeps_up(r):
    return (r["ticks_per_s"] >= 29 and r["late"] == 0 and r["loop_lag_ms_p99"] < 50
            and r["states_per_s_min"] >= 28)


def _show(r):
    return (f"{r['variant']:12s} {r['rooms']:3d} rooms x {r['people']}: CPU {r['cpu_pct']:5.1f}%  "
            f"tick {r['tick_ms_avg']:.2f}/{r['tick_ms_p99']:.2f} ms  lag p99 {r['loop_lag_ms_p99']:.1f} ms  "
            f"states/s min {r['states_per_s_min']:.1f}  gap p99 {r['gap_ms_p99']:.0f} ms  "
            f"wire {r['wire_kbit_per_player']:.1f} kbit/s  rebuilt {r['checked']} bad {r['rebuild_failures']}  "
            f"{r['frame_kinds']}  browsers {r['browser_cpu_pct_max']:.0f}%  {'ok' if keeps_up(r) else 'BEHIND'}")


def fixed(loads=((40, 4, "classic"), (20, 8, "grand")), repeats=5, seconds=15, seed=0):
    from bench.wire.bench import _boot_ci, _save
    rng = random.Random(seed)
    runs = []
    for rooms, people, map_name in loads:
        for rep in range(repeats):
            order = list(VARIANTS)
            rng.shuffle(order)
            for v in order:
                r = one_run(v, rooms, people, map_name, seconds)
                r["repeat"] = rep
                runs.append(r)
                print(_show(r), file=sys.stderr, flush=True)
    _save("sockets", {"seconds": seconds, "repeats": repeats, "runs": runs})
    print(f"\nA real server on one core, browsers on others; {repeats} runs of {seconds:g} s each, variants in turn:\n")
    print("| load | variant | server CPU (median, 95% interval) | vs today | tick p99 | wire per player | "
          "states/s (slowest browser) | rebuilt OK |")
    print("|---|---|---|---|---|---|---|---|")
    for rooms, people, map_name in loads:
        mine = [r for r in runs if r["rooms"] == rooms and r["people"] == people]
        base = {r["repeat"]: r["cpu_pct"] for r in mine if r["variant"] == "json+deflate"}
        for v in VARIANTS:
            rs = sorted((r for r in mine if r["variant"] == v), key=lambda r: r["repeat"])
            cpu = [r["cpu_pct"] for r in rs]
            diff = [r["cpu_pct"] - base[r["repeat"]] for r in rs]
            lo, hi = _boot_ci(cpu)
            dlo, dhi = _boot_ci(diff)
            print(f"| {rooms} rooms of {people} ({map_name}) | {v} | {statistics.median(cpu):.1f}% ({lo:.1f}–{hi:.1f}) "
                  f"| {statistics.median(diff):+.1f} pts ({dlo:+.1f} to {dhi:+.1f}) "
                  f"| {statistics.median(r['tick_ms_p99'] for r in rs):.2f} ms "
                  f"| {statistics.median(r['wire_kbit_per_player'] for r in rs):.1f} kbit/s "
                  f"| {min(r['states_per_s_min'] for r in rs):.1f} "
                  f"| {sum(r['checked'] for r in rs)} states, {sum(r['rebuild_failures'] for r in rs)} failed |")
    return runs


def capacity(people=8, map_name="grand", start=15, step=3, repeats=2, seconds=12, seed=1):
    from bench.wire.bench import _save
    rng = random.Random(seed)
    found = {v: [] for v in VARIANTS}
    log = []
    for rep in range(repeats):
        order = list(VARIANTS)
        rng.shuffle(order)
        for v in order:
            n, best = start, None
            while True:
                r = one_run(v, n, people, map_name, seconds)
                r["repeat"] = rep
                log.append(r)
                print(_show(r), file=sys.stderr, flush=True)
                if not keeps_up(r):
                    break
                best = n
                n += step
            found[v].append(best)
    _save("capacity", {"people": people, "map": map_name, "step": step, "found": found, "runs": log})
    print(f"\nMost rooms of {people} ({map_name}) one core keeps up with (all ticks on time, every browser"
          f" getting 30 states a second), in steps of {step}, each of {repeats} tries:\n")
    print("| variant | rooms | players |")
    print("|---|---|---|")
    for v in VARIANTS:
        print(f"| {v} | {', '.join(str(x) for x in found[v])} | "
              f"{', '.join(str(x * people) if x else '-' for x in found[v])} |")
    return found


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "server":
        variant, rooms, people, map_name, seconds = argv[1:6]
        r = asyncio.run(run_server(variant, int(rooms), int(people), map_name, float(seconds)))
        print(json.dumps(r))
        return
    if argv and argv[0] == "browsers":
        url, variant, people, out_path, *codes = argv[1:]
        asyncio.run(browsers(url, variant, int(people), out_path, codes))
        return
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=("fixed", "capacity", "one"))
    p.add_argument("--repeats", type=int, default=None)
    p.add_argument("--seconds", type=float, default=15)
    p.add_argument("--variant", default="json+deflate")
    p.add_argument("--rooms", type=int, default=10)
    p.add_argument("--people", type=int, default=8)
    p.add_argument("--map", default="grand")
    a = p.parse_args(argv)
    if a.what == "one":
        print(_show(one_run(a.variant, a.rooms, a.people, a.map, a.seconds)))
    elif a.what == "fixed":
        fixed(repeats=a.repeats or 5, seconds=a.seconds)
    else:
        capacity(repeats=a.repeats or 2)


if __name__ == "__main__":
    main()
