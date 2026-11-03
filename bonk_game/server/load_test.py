"""How many rooms can one server run? Runs N rooms of 10 at once and reports
CPU, tick time and bandwidth, for N = 1, 5, 10, 20, ... until the server
can't keep up.

    python -m bonk_game.server.load_test [--seconds 10] [--rooms 1,5,10,20,40]
                                         [--map grand] [--players bots|people]
                                         [--sockets] [--full]

Each room is a real Room running a real match, with 10 members who are
sent every message (counted, then thrown away). --players bots: bots play
every ball (the worst case: bots cost CPU that people don't).
--players people: the balls belong to "people" pressing random buttons.

--sockets: the members are real WebSocket connections to a real server
(the browsers are a second process, so their CPU isn't counted). Slower to
set up, and the honest number: sending to sockets, compression included,
costs as much as the game. Without it, messages are only counted, not sent.

"JSON" is the size of the messages; "wire" (--sockets) is what the
WebSocket frames came to after compression (permessage-deflate, which
browsers ask for and so does this test). TCP/IP headers add about 50 bytes
per message on top.

--full: send the whole state every tick, as before delta.py, to compare.

The server is one Python process, so it uses one CPU core; the numbers
are per core.
"""
import argparse
import asyncio
import os
import random
import resource
import subprocess
import sys
import time

from bonk_game.server import delta, limits, metrics, room as room_mod
from bonk_game.server.room import RoomManager

PEOPLE = 10
TICK_HZ = room_mod.TICK_HZ


class Counter:
    """Stands in for a browser: counts what it's sent."""

    def __init__(self):
        self.bytes = 0

    async def __call__(self, msg):
        self.bytes += len(msg) if isinstance(msg, str) else 200


def cpu_seconds():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


async def fake_person(room, slot, rng, stop):
    """Presses random buttons a few times a second."""
    while not stop.is_set():
        if room.match is not None:
            room.match.set_input(slot, [int(rng.random() < p) for p in (0.15, 0.4, 0.1, 0.4, 0.3)])
        await asyncio.sleep(rng.uniform(0.1, 0.5))


async def browsers(url, codes, compress=15):
    """The other end of --sockets: PEOPLE connections per room that read
    everything and throw it away. Runs until killed."""
    import aiohttp
    from bonk_game.server.web import VERSION

    gate = asyncio.Semaphore(20)  # don't connect all at once (the listen backlog)

    async def one(session, code, k):
        for attempt in range(20):
            try:
                async with gate:
                    # compress=15: ask for permessage-deflate, as browsers do
                    ws = await session.ws_connect(f"{url}/ws/{code}", max_msg_size=0,
                                                  compress=compress)
                break
            except aiohttp.ClientError:
                await asyncio.sleep(0.2 * (attempt + 1))
        else:
            raise RuntimeError(f"couldn't connect to {code}")
        async with ws:
            await ws.send_json({"type": "hello", "name": f"P{k}", "token": f"{code}-{k}",
                                "version": VERSION})
            async for _ in ws:
                pass

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as session:
        await asyncio.gather(*(one(session, c, k) for c in codes for k in range(PEOPLE)))


async def serve(rooms):
    """A real server on a free local port. Returns (runner, url)."""
    from aiohttp import web as aioweb
    from bonk_game.server.web import make_app
    limits.CONNECTIONS_PER_IP = 10 ** 6   # every "browser" is on 127.0.0.1
    limits.MAX_ROOMS = 10 ** 6
    runner = aioweb.AppRunner(make_app(rooms), handle_signals=False)
    await runner.setup()
    site = aioweb.TCPSite(runner, "127.0.0.1", 0, backlog=1024)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


async def run_level(n_rooms, seconds, map_name, players, sockets=False, seed=0, compress=True):
    metrics.STATS = metrics.Stats()
    rooms = RoomManager(rng=random.Random(seed))
    counters, stop, people = [], asyncio.Event(), []
    rng = random.Random(seed)
    runner = client = None
    made = [rooms.create() for _ in range(n_rooms)]
    if sockets:
        runner, url = await serve(rooms)
        client = subprocess.Popen([sys.executable, "-m", "bonk_game.server.load_test", "--browsers", url]
                                  + [r.code for r in made] + ([] if compress else ["--no-compress"]),
                                  env={**os.environ})
        end = time.monotonic() + 120
        while any(len(r.connected) < PEOPLE for r in made):
            if time.monotonic() > end or client.poll() is not None:
                client.kill()
                await runner.cleanup()
                raise RuntimeError("the browsers didn't all connect")
            await asyncio.sleep(0.1)
    for room in made:
        if not sockets:
            for k in range(PEOPLE):
                c = Counter()
                counters.append(c)
                await room.join(f"p{k}", f"P{k}", c)
        room.settings.update(map=map_name, first_to=1000, bots=[])
        await room.start()
        for k in range(PEOPLE):
            if players == "bots":
                room.match.stand_in(k)
            else:
                people.append(asyncio.ensure_future(fake_person(room, k, rng, stop)))
    # Let everything get going, then measure
    await asyncio.sleep(1.0)
    stats = metrics.STATS
    ticks0, late0 = stats.ticks_total, stats.late_ticks
    sent = lambda: stats.bytes_sent if sockets else sum(c.bytes for c in counters)
    bytes0 = sent()
    wire0 = stats.wire_bytes if sockets else None
    stats.ticks.clear()
    cpu0, t0 = cpu_seconds(), time.monotonic()
    loop = asyncio.get_running_loop()
    lag = []

    async def watch_lag():  # how late the event loop wakes up
        while not stop.is_set():
            want = loop.time() + 0.05
            await asyncio.sleep(0.05)
            lag.append(loop.time() - want)
    watcher = asyncio.ensure_future(watch_lag())
    await asyncio.sleep(seconds)
    wall = time.monotonic() - t0
    cpu = cpu_seconds() - cpu0
    bytes1 = sent()
    wire1 = stats.wire_bytes if sockets else None
    stop.set()
    await watcher
    for p in people:
        p.cancel()
    avg, p99 = stats.tick_ms()
    ticks = stats.ticks_total - ticks0
    for room in rooms.rooms.values():
        await room.stop()
    if client is not None:
        client.kill()
        client.wait()
        await runner.cleanup()
    await asyncio.sleep(0)
    lag.sort()
    return {
        "rooms": n_rooms,
        "cpu_pct": 100 * cpu / wall,
        "tick_ms_avg": avg,
        "tick_ms_p99": p99,
        "ticks_per_s": ticks / wall / n_rooms,
        "late": stats.late_ticks - late0,
        "loop_lag_ms_p99": 1000 * lag[int(len(lag) * 0.99)] if lag else 0.0,
        "kb_per_s_room": (bytes1 - bytes0) / wall / n_rooms / 1000,
        "wire_kb_per_s_room": (None if wire0 is None or wire1 is None
                               else (wire1 - wire0) / wall / n_rooms / 1000),
    }


INTERP_DELAY_MS = 50  # the browser draws this far behind (js/core.js), so lateness under it doesn't show


def keeps_up(r):
    return (r["ticks_per_s"] >= TICK_HZ * 0.97 and r["loop_lag_ms_p99"] < INTERP_DELAY_MS
            and not r["late"])


def _rate(kb):
    return "-" if kb is None else f"{kb:.1f} KB/s ({kb * 8 / 1000:.2f} Mbit/s)"


def table(results):
    head = ("| rooms | CPU (1 core) | tick avg | tick p99 | ticks/s per room | event-loop lag p99 "
            "| JSON per room | wire per room | keeps up |\n|---|---|---|---|---|---|---|---|---|")
    rows = [f"| {r['rooms']} | {r['cpu_pct']:.0f}% | {r['tick_ms_avg']:.2f} ms | {r['tick_ms_p99']:.2f} ms "
            f"| {r['ticks_per_s']:.1f} | {r['loop_lag_ms_p99']:.1f} ms | {_rate(r['kb_per_s_room'])} "
            f"| {_rate(r['wire_kb_per_s_room'])} | {'yes' if keeps_up(r) else 'no'} |"
            for r in results]
    return "\n".join([head] + rows)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--seconds", type=float, default=10.0, help="how long to measure each level")
    p.add_argument("--rooms", default="1,5,10,20,40,80", help="room counts to try, in order")
    p.add_argument("--map", default="grand", help="a map for 10 players (grand, decks)")
    p.add_argument("--players", choices=("bots", "people"), default="bots")
    p.add_argument("--sockets", action="store_true", help="send over real WebSockets")
    p.add_argument("--full", action="store_true", help="send whole states, not changes")
    p.add_argument("--no-compress", action="store_true",
                   help="browsers that don't ask for compression (--sockets)")
    p.add_argument("--browsers", nargs="+", help=argparse.SUPPRESS)  # (the --sockets helper)
    args = p.parse_args(argv)
    if args.browsers:
        asyncio.run(browsers(args.browsers[0], args.browsers[1:], 0 if args.no_compress else 15))
        return
    if args.full:
        delta.KEYFRAME_EVERY = 1
    results = []
    for n in (int(x) for x in args.rooms.split(",")):
        r = asyncio.run(run_level(n, args.seconds, args.map, args.players, args.sockets,
                                  compress=not args.no_compress))
        results.append(r)
        wire = r["wire_kb_per_s_room"]
        print(f"{n:4d} rooms: CPU {r['cpu_pct']:5.1f}%  tick {r['tick_ms_avg']:.2f}/{r['tick_ms_p99']:.2f} ms  "
              f"{r['ticks_per_s']:.1f} ticks/s  lag p99 {r['loop_lag_ms_p99']:.1f} ms  "
              f"JSON {r['kb_per_s_room']:.1f} KB/s"
              + ("" if wire is None else f", wire {wire:.1f} KB/s") + " per room  "
              f"{'ok' if keeps_up(r) else 'BEHIND'}", flush=True)
        if not keeps_up(r):
            break
    print()
    how = "over WebSockets" if args.sockets else "counted, not sent"
    what = "whole states" if args.full else "changes (delta.py)"
    print(f"{PEOPLE} per room on {args.map}, {args.players} playing, {what} {how}, "
          f"{args.seconds:g} s per level:")
    print()
    print(table(results))
    ok = [r for r in results if keeps_up(r) and r["cpu_pct"] < 70]
    if ok:
        best = ok[-1]
        rate = best["wire_kb_per_s_room"] or best["kb_per_s_room"]
        print(f"\nOne core comfortably runs {best['rooms']} rooms of {PEOPLE} "
              f"(CPU {best['cpu_pct']:.0f}%), sending about "
              f"{rate * best['rooms'] * 8 / 1000:.1f} Mbit/s.")


if __name__ == "__main__":
    main()
