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
    GET  /metrics        numbers for whoever runs the server (Prometheus
                         text; ?format=json for JSON). If BONK_METRICS_TOKEN
                         is set, send it as "Authorization: Bearer <token>".

The page is served with every /static/ URL ending in ?v=<VERSION>, a hash
of the client files, so browsers can cache them for good and still pick up
a new client after a deploy.

WebSocket protocol (JSON text messages):
  browser -> server
    {"type": "hello", "name": "Sam", "token": "<random id>", "version": "<VERSION>"}
        first message. A different version (a tab opened before a deploy)
        gets {"type": "error", "fatal": true, "refresh": true} back. With
        "reopen": true, a room that doesn't exist (the server restarted) is
        made again with the same code; "host": true says you were its host,
        so you get that back (once, within room.REOPEN_GRACE seconds).
    {"type": "input", "b": [up, left, down, right, heavy]}      0/1 each, on change
    {"type": "name", "name": "Sam"}
    host only:
    {"type": "settings", "map": "platform", "first_to": 5, "bots": ["bot:medium"]}
    {"type": "start"}
    {"type": "lobby"}                                          back from results
  server -> browser
    welcome, lobby, match (once per match), state (30 times a second),
    results, error, notice, restart. See room.py and match.py.

On SIGTERM the server stops taking connections, lets the matches being
played finish (up to BONK_DRAIN_SECONDS), then sends every room "restart"
and closes. Browsers reconnect to the new server and reopen their room.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import traceback

from aiohttp import WSCloseCode, WSMsgType, web

from bonk_game.envs.utils.maps import MAPS, agent_dir
from bonk_game.server import limits, metrics
from bonk_game.server.room import RoomFull, RoomManager, ServerFull, valid_code

STATIC = os.path.join(os.path.dirname(__file__), "static")
AGENT_KINDS = ("ppo", "a2c", "dqn", "ars", "bad")
SWEEP_EVERY = 5.0

ROOMS = web.AppKey("rooms", object)
ROOM_LIMIT = web.AppKey("room_limit", object)
CONNECTIONS = web.AppKey("connections", dict)
SWEEPER = web.AppKey("sweeper", object)
SOCKETS = web.AppKey("sockets", object)
MAX_MESSAGE = 4096
# Bump when a message changes in a way an old page can't handle. (Any change
# to the client files changes VERSION anyway.)
PROTOCOL = 1
DRAIN_SECONDS = limits._env("BONK_DRAIN_SECONDS", 120.0)
METRICS_TOKEN = os.environ.get("BONK_METRICS_TOKEN", "")


def client_version(static=STATIC):
    """A short hash of the protocol number and every client file."""
    h = hashlib.sha256(f"protocol {PROTOCOL}".encode())
    for root, dirs, files in sorted(os.walk(static)):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            h.update(os.path.relpath(path, static).encode())
            with open(path, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:12]


VERSION = client_version()


def render_index(version=VERSION):
    """index.html with ?v=<version> on every /static/ URL and the version
    in a meta tag (the page sends it back in "hello")."""
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        page = f.read()
    page = re.sub(r'((?:src|href)="/static/[^"?]+)"', rf'\1?v={version}"', page)
    return page.replace("<head>", f'<head>\n  <meta name="bonk-version" content="{version}">', 1)


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
            metrics.STATS.sent(len(text))
        except (ConnectionResetError, RuntimeError):
            pass
    return send


PAGE = web.AppKey("page", str)


async def index(request):
    return web.Response(text=request.app[PAGE], content_type="text/html",
                        headers={"Cache-Control": "no-cache"})


@web.middleware
async def cache_headers(request, handler):
    """Versioned client files are cached for good; anything else is checked
    with the server each time."""
    response = await handler(request)
    if request.path.startswith("/static/"):
        if request.query.get("v") == VERSION:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
    return response


async def create_room(request):
    if request.app[ROOMS].draining:
        return web.json_response({"error": "The server is restarting. Try again in a moment."},
                                 status=503)
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


async def metrics_page(request):
    if METRICS_TOKEN:
        given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), METRICS_TOKEN.encode()):
            raise web.HTTPUnauthorized(text="Send the metrics token.")
    snap = metrics.STATS.snapshot(request.app[ROOMS])
    snap["version"] = VERSION
    headers = {"Cache-Control": "no-store"}
    if request.query.get("format") == "json":
        return web.json_response(snap, headers=headers)
    snap.pop("version")
    text = f'# TYPE bonk_info gauge\nbonk_info{{version="{VERSION}"}} 1\n' + metrics.prometheus(snap)
    return web.Response(text=text, content_type="text/plain", headers=headers)


async def websocket(request):
    rooms = request.app[ROOMS]
    conns = request.app[CONNECTIONS]
    ip = limits.client_ip(request)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MESSAGE)
    await ws.prepare(request)
    code = request.match_info["code"].upper()
    send = _sender(ws)

    async def refuse(text, **extra):
        await send({"type": "error", "message": text, "fatal": True, **extra})
        await ws.close()
        return ws

    if conns.get(ip, 0) >= limits.CONNECTIONS_PER_IP:
        return await refuse("Too many connections from your network.")
    conns[ip] = conns.get(ip, 0) + 1
    request.app[SOCKETS].add(ws)
    metrics.STATS.connections += 1

    bucket = limits.TokenBucket(limits.MESSAGES_PER_SECOND, limits.MESSAGE_BURST)
    dropped = 0
    token = None
    room = None
    try:
        hello = await ws.receive(timeout=10)
        if hello.type != WSMsgType.TEXT:
            return ws
        msg = json.loads(hello.data)
        if not isinstance(msg, dict) or msg.get("type") != "hello":
            return ws
        if msg.get("version") != VERSION:
            metrics.STATS.refused_old_clients += 1
            return await refuse("The game has been updated. Refresh the page to keep playing.",
                                refresh=True)
        room = rooms.get(code)
        if room is None and msg.get("reopen") is True and valid_code(code):
            # Back after a server restart: make the room again (counts as making a room)
            if request.app[ROOM_LIMIT].allow(ip):
                try:
                    room = rooms.create(code)
                    room.reopened_at = time.monotonic()
                except ServerFull:
                    pass
        if room is None:
            return await refuse("That room doesn't exist (or has closed).")
        token = str(msg.get("token") or "")[:64] or secrets.token_hex(12)
        try:
            await room.join(token, msg.get("name"), send, was_host=msg.get("host") is True)
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
                try:
                    await room.handle(token, msg)
                except Exception as e:  # a bug, not the browser's fault: log it and carry on
                    metrics.event("error", logging.ERROR, room=room.code, where="handle",
                                  message=str(msg.get("type"))[:20], error=repr(e),
                                  trace=traceback.format_exc())
    except (asyncio.TimeoutError, ValueError):
        pass
    finally:
        conns[ip] -= 1
        if not conns[ip]:
            del conns[ip]
        metrics.STATS.connections -= 1
        request.app[SOCKETS].discard(ws)
        if token is not None:
            await room.disconnect(token, send)
    return ws


async def _sweeper(app):
    while True:
        await asyncio.sleep(SWEEP_EVERY)
        await app[ROOMS].sweep()


async def _start_background(app):
    app[SWEEPER] = asyncio.ensure_future(_sweeper(app))


async def _shutdown(app, drain=None):
    """SIGTERM: the listening socket is already closed (no new connections).
    Let matches finish, tell everyone, and close the WebSockets."""
    await app[ROOMS].drain(DRAIN_SECONDS if drain is None else drain)
    for ws in list(app[SOCKETS]):
        await ws.close(code=WSCloseCode.SERVICE_RESTART, message=b"server restarting")


async def _stop_background(app):
    app[SWEEPER].cancel()
    for room in list(app[ROOMS].rooms.values()):
        await room.stop()


def make_app(rooms=None):
    app = web.Application(middlewares=[cache_headers])
    app[ROOMS] = rooms or RoomManager(AgentStore())
    app[ROOM_LIMIT] = limits.PerKey(limits.ROOMS_PER_IP / 60, limits.ROOMS_PER_IP)
    app[CONNECTIONS] = {}  # ip -> open WebSockets
    app[SOCKETS] = set()  # open WebSockets, closed on shutdown
    app[PAGE] = render_index()
    app.router.add_get("/", index)
    app.router.add_get("/r/{code}", index)
    app.router.add_post("/api/rooms", create_room)
    app.router.add_get("/api/rooms/{code}", room_info)
    app.router.add_get("/ws/{code}", websocket)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/metrics", metrics_page)
    app.router.add_static("/static/", STATIC)
    app.on_startup.append(_start_background)
    app.on_shutdown.append(_shutdown)
    app.on_cleanup.append(_stop_background)
    return app


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Run the bonk web server.")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = parser.parse_args(argv)
    metrics.setup_logging()
    print(f"bonk server on http://{args.host}:{args.port}  ({len(MAPS)} maps, client {VERSION})")
    metrics.event("server_started", host=args.host, port=args.port, version=VERSION, maps=len(MAPS))
    # The drain does the waiting; a few seconds more lets the last messages out
    web.run_app(make_app(), host=args.host, port=args.port, print=None,
                shutdown_timeout=5.0)
    metrics.event("server_stopped")
