"""The web server: serves the browser client and runs rooms over WebSockets.

    python -m bonk_game.server [--host 0.0.0.0] [--port 8000]

Routes:
    GET  /               the client (home screen)
    GET  /r/<code>       the client, opening room <code>
    GET  /static/...     client files
    POST /api/rooms      create a room -> {"room": "ABCD"}
    GET  /api/rooms/<code>   {"room": "ABCD", "players": 3} or 404
    GET  /ws/<code>      WebSocket for one browser in a room
    GET  /healthz        "ok"

WebSocket protocol (JSON text messages):
  browser -> server
    {"type": "hello", "name": "Sam", "token": "<random id>"}   first message
    {"type": "input", "b": [up, left, down, right, heavy]}      0/1 each, on change
    {"type": "name", "name": "Sam"}
    host only:
    {"type": "settings", "map": "platform", "first_to": 5, "bots": ["bot:medium"]}
    {"type": "start"}
    {"type": "lobby"}                                          back from results
  server -> browser
    welcome, lobby, match (once per match), state (30 times a second),
    results, error. See room.py and match.py.
"""
import asyncio
import json
import os
import secrets

from aiohttp import WSMsgType, web

from bonk_game.envs.utils.maps import MAPS, agent_dir
from bonk_game.server import limits
from bonk_game.server.room import RoomFull, RoomManager, ServerFull

STATIC = os.path.join(os.path.dirname(__file__), "static")
AGENT_KINDS = ("ppo", "a2c", "dqn", "ars", "bad")
SWEEP_EVERY = 5.0

ROOMS = web.AppKey("rooms", object)
ROOM_LIMIT = web.AppKey("room_limit", object)
CONNECTIONS = web.AppKey("connections", dict)
SWEEPER = web.AppKey("sweeper", object)
MAX_MESSAGE = 4096


class AgentStore:
    """Trained agents the server can use as players, if any are saved and
    stable-baselines3 is installed. Loaded on first use, per map."""

    def __init__(self):
        self._loaded = {}
        try:
            import stable_baselines3  # noqa: F401
            self.available = True
        except ImportError:
            self.available = False

    def names(self, map_name):
        if not self.available:
            return []
        d = agent_dir(map_name)
        return [k for k in AGENT_KINDS if os.path.exists(f"{d}/{k}.zip")]

    def load(self, map_name):
        if map_name not in self._loaded:
            from bonk_game.envs.utils.testing import load_agents, model_classes
            self._loaded[map_name] = load_agents(model_classes(), map_name) if self.available else {}
        return self._loaded[map_name]


def _sender(ws):
    async def send(msg):
        if ws.closed:
            return
        text = msg if isinstance(msg, str) else json.dumps(msg, separators=(",", ":"))
        try:
            await ws.send_str(text)
        except (ConnectionResetError, RuntimeError):
            pass
    return send


async def index(request):
    return web.FileResponse(os.path.join(STATIC, "index.html"),
                            headers={"Cache-Control": "no-cache"})


async def create_room(request):
    if not request.app[ROOM_LIMIT].allow(limits.client_ip(request)):
        return web.json_response({"error": "You're making rooms too quickly. Try again in a minute."},
                                 status=429)
    try:
        room = request.app[ROOMS].create()
    except ServerFull:
        return web.json_response({"error": "The server is full right now. Try again later."},
                                 status=503)
    return web.json_response({"room": room.code})


async def room_info(request):
    room = request.app[ROOMS].get(request.match_info["code"])
    if room is None:
        raise web.HTTPNotFound(text="No such room")
    return web.json_response({"room": room.code, "players": len(room.connected)})


async def healthz(request):
    return web.Response(text="ok")


async def websocket(request):
    rooms = request.app[ROOMS]
    conns = request.app[CONNECTIONS]
    ip = limits.client_ip(request)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MESSAGE)
    await ws.prepare(request)
    room = rooms.get(request.match_info["code"])
    send = _sender(ws)

    async def refuse(text):
        await send({"type": "error", "message": text, "fatal": True})
        await ws.close()
        return ws

    if room is None:
        return await refuse("That room doesn't exist (or has closed).")
    if conns.get(ip, 0) >= limits.CONNECTIONS_PER_IP:
        return await refuse("Too many connections from your network.")
    conns[ip] = conns.get(ip, 0) + 1

    bucket = limits.TokenBucket(limits.MESSAGES_PER_SECOND, limits.MESSAGE_BURST)
    dropped = 0
    token = None
    try:
        hello = await ws.receive(timeout=10)
        if hello.type != WSMsgType.TEXT:
            return ws
        msg = json.loads(hello.data)
        if msg.get("type") != "hello":
            return ws
        token = str(msg.get("token") or "")[:64] or secrets.token_hex(12)
        try:
            await room.join(token, msg.get("name"), send)
        except RoomFull as e:
            token = None
            return await refuse(str(e))

        async for raw in ws:
            if raw.type != WSMsgType.TEXT:
                continue
            if not bucket.allow():
                dropped += 1
                if dropped > limits.MAX_DROPPED:
                    await send({"type": "error", "message": "Disconnected for sending too much.",
                                "fatal": True})
                    break
                continue
            try:
                msg = json.loads(raw.data)
            except ValueError:
                continue
            if isinstance(msg, dict):
                await room.handle(token, msg)
    except (asyncio.TimeoutError, ValueError):
        pass
    finally:
        conns[ip] -= 1
        if not conns[ip]:
            del conns[ip]
        if token is not None:
            await room.disconnect(token, send)
    return ws


async def _sweeper(app):
    while True:
        await asyncio.sleep(SWEEP_EVERY)
        await app[ROOMS].sweep()


async def _start_background(app):
    app[SWEEPER] = asyncio.ensure_future(_sweeper(app))


async def _stop_background(app):
    app[SWEEPER].cancel()
    for room in list(app[ROOMS].rooms.values()):
        await room.stop()


def make_app(rooms=None):
    app = web.Application()
    app[ROOMS] = rooms or RoomManager(AgentStore())
    app[ROOM_LIMIT] = limits.PerKey(limits.ROOMS_PER_IP / 60, limits.ROOMS_PER_IP)
    app[CONNECTIONS] = {}  # ip -> open WebSockets
    app.router.add_get("/", index)
    app.router.add_get("/r/{code}", index)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_get("/api/rooms/{code}", room_info)
    app.router.add_get("/ws/{code}", websocket)
    app.router.add_get("/healthz", healthz)
    app.router.add_static("/static/", STATIC)
    app.on_startup.append(_start_background)
    app.on_cleanup.append(_stop_background)
    return app


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Run the bonk web server.")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = parser.parse_args(argv)
    print(f"bonk server on http://{args.host}:{args.port}  ({len(MAPS)} maps)")
    web.run_app(make_app(), host=args.host, port=args.port, print=None)
