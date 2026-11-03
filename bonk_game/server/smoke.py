"""Check a running server end to end, e.g. right after a deploy:

    python -m bonk_game.server.smoke https://bonk.example.com [--seconds 10]

Loads the page, makes a room, joins it over the WebSocket (wss:// for an
https:// address), starts a match against a bot and measures ping and how
steadily states arrive from where you run it. Exits 1 if anything fails.
"""
import argparse
import asyncio
import json
import re
import secrets
import sys
import time

import aiohttp

LATE_GAP = 0.1  # s between states (they come every 33 ms)


def _ws_url(base, code):
    return re.sub(r"^http", "ws", base.rstrip("/")) + f"/ws/{code}"


async def smoke(base, seconds=10.0, out=print):
    base = base.rstrip("/")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=seconds + 30)) as http:
        async with http.get(base + "/healthz") as res:
            if res.status != 200:
                raise RuntimeError(f"/healthz answered {res.status}")
        t0 = time.perf_counter()
        async with http.get(base + "/") as res:
            page = await res.text()
        out(f"page: {res.status}, {len(page)} bytes in {(time.perf_counter() - t0) * 1000:.0f} ms")
        m = re.search(r'<meta name="bonk-version" content="([^"]+)"', page)
        if not m:
            raise RuntimeError("the page has no bonk-version (not a bonk server?)")
        version = m.group(1)
        async with http.post(base + "/api/rooms") as res:
            body = await res.json()
            if res.status != 200:
                raise RuntimeError(f"making a room: {res.status} {body}")
        code = body["room"]
        async with http.ws_connect(_ws_url(base, code), compress=15, heartbeat=20) as ws:
            out(f"room {code}: connected to {_ws_url(base, code)}"
                f" ({'compressed' if ws.compress else 'not compressed'})")
            await ws.send_json({"type": "hello", "name": "smoke test", "token": secrets.token_hex(8),
                                "version": version})
            await ws.send_json({"type": "settings", "map": "classic", "bots": ["bot:easy"], "first_to": 10})
            await ws.send_json({"type": "start"})
            pings, gaps, states = [], [], 0
            last = None
            started = time.perf_counter()
            next_ping = started

            async def reader():
                nonlocal states, last
                async for raw in ws:
                    if raw.type != aiohttp.WSMsgType.TEXT:
                        continue
                    msg = json.loads(raw.data)
                    kind = msg.get("type")
                    if kind == "error":
                        raise RuntimeError(f"server said: {msg.get('message')}")
                    if kind == "pong":
                        pings.append((time.perf_counter() - msg["t"]) * 1000)
                    elif kind in ("state", "d"):
                        now = time.perf_counter()
                        if last is not None:
                            gaps.append(now - last)
                        last = now
                        states += 1

            task = asyncio.ensure_future(reader())
            try:
                while time.perf_counter() - started < seconds:
                    if task.done():
                        task.result()
                        raise RuntimeError("the server closed the connection")
                    if time.perf_counter() >= next_ping:
                        await ws.send_json({"type": "ping", "t": time.perf_counter()})
                        next_ping += 0.5
                    await asyncio.sleep(0.05)
            finally:
                task.cancel()
    took = time.perf_counter() - started
    if not states:
        raise RuntimeError("no match states arrived")
    p = sorted(pings)
    q = (lambda f: p[min(len(p) - 1, int(len(p) * f))]) if p else (lambda f: float("nan"))
    late = sum(1 for g in gaps if g > LATE_GAP)
    result = {"ping_min": p[0] if p else None, "ping_med": q(0.5), "ping_p95": q(0.95),
              "states_per_second": states / took, "late_states": late,
              "worst_gap_ms": max(gaps) * 1000 if gaps else None}
    out(f"ping: {result['ping_min']:.0f} min, {result['ping_med']:.0f} median, {result['ping_p95']:.0f} ms p95"
        f" ({len(p)} pings)")
    out(f"states: {result['states_per_second']:.1f} a second, {late} late (over 100 ms),"
        f" worst gap {result['worst_gap_ms']:.0f} ms")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a running bonk server end to end.")
    parser.add_argument("url", help="e.g. https://bonk.example.com or http://localhost:8000")
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        r = asyncio.run(smoke(args.url, args.seconds))
    except Exception as e:  # noqa: BLE001 - say what failed, in one line
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    ok = r["states_per_second"] >= 25
    print("ok" if ok else "FAILED: states aren't arriving 30 times a second")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
