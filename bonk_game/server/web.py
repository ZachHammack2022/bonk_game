"""The web server: serves the browser client and runs rooms over WebSockets.

    python -m bonk_game.server [--host 0.0.0.0] [--port 8000]

Routes:
    GET  /               the client (home screen)
    GET  /r/<code>       the client, opening room <code>
    GET  /static/...     client files
    GET  /play           the game browser (the page itself; the client draws it)
    POST /api/rooms      create a room -> {"room": "ABCD", "name": ..., "password": "k7mq2x"};
                         send {"name": "Sam's room", "password": false} for one
                         without a password (a password is made up otherwise)
    GET  /api/public     the game browser's list: every room (name, whether it
                         has a password, never the password), people online
    POST /api/quickplay  a public room to join -> {"room": "ABCD"} (room.py)
    GET  /api/friends    your friends (and where they're playing) and friend requests
    POST /api/friends/{id}    say yes to a friend request; DELETE: unfriend, or turn one down
    GET  /api/rooms/<code>   {"room": "ABCD", "players": 3} or 404
    GET  /leaderboard    the leaderboard (the page itself); /api/leaderboard is
                         its data: the best signed-in players by rating, and
                         yours when signed in (auth.py, rating.py)
    GET  /ws/<code>      WebSocket for one browser in a room
    GET  /healthz        "ok"
    GET  /metrics        numbers for whoever runs the server (Prometheus
                         text; ?format=json for JSON). If BONK_METRICS_TOKEN
                         is set, send it as "Authorization: Bearer <token>".
    GET  /api/playtest   the latest playtest reports and browser errors
                         (playtest.py; same token as /metrics)
    GET  /api/reports    the latest player reports (moderation.py; same token)
    GET  /admin          a page charting the server's numbers, now and over the
                         last 90 days, and who comes back (retention, from
                         metrics.Retention); you paste the metrics token into it
    GET  /api/admin/metrics?range=<seconds>   what that page shows (same token;
                         unlike /metrics, refused if BONK_METRICS_TOKEN isn't set)
    GET  /manifest.webmanifest   the web app's manifest (Add to Home Screen)
    GET  /privacy        what the site keeps about people
    GET  /terms          the terms of use
    /auth/..., /api/me   signing in with Google and your account, when
                         GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set
                         (auth.py, accounts.py)

The page is served with every /static/ URL ending in ?v=<VERSION>, a hash
of the client files, so browsers can cache them for good and still pick up
a new client after a deploy.

WebSocket protocol (JSON text messages):
  browser -> server
    {"type": "hello", "name": "Sam", "token": "<random id>", "version": "<VERSION>",
     "password": "k7mq2x", "tz": 60}
        first message. password: the room's, if it has one (people already
        in the room don't need it to reconnect); without it (or a wrong one)
        the reply is {"type": "error", "fatal": true, "password": true}. A different version (a tab opened before a deploy)
        gets {"type": "error", "fatal": true, "refresh": true} back. With
        "reopen": true, a room that doesn't exist (the server restarted) is
        made again with the same code; "host": true says you were its host,
        so you get that back (once, within room.REOPEN_GRACE seconds).
    {"type": "input", "b": [up, left, down, right, heavy]}      0/1 each, on change
    {"type": "name", "name": "Sam"}
    {"type": "away"} / {"type": "back"}   off to the lobby during a match (a
                                          bot plays for you), and back
    {"type": "report_player", "id": "<their public id>", "reason": "name", "note": "..."}
    {"type": "report", "ping": {...}, ...}     after a match: what it saw (playtest.py)
    {"type": "client_error", "message": "...", "where": "draw.js:12"}
    host only:
    {"type": "settings", "map": "platform", "first_to": 5, "bots": ["bot:medium"],
     "name": "Sam's room", "password": true}   (true: a new random one; null: none)
    {"type": "start"}
    {"type": "lobby"}                                          back from results
  server -> browser
    welcome, lobby, match (once per match), 30 times a second a state or,
    mostly, "d" (just what changed: delta.py), results, error, notice,
    restart, and "seat" when someone who joined during the match takes
    over a bot ({"slot": k, "info": the slot, as in "match"}). People are
    known by a public id ("you" in welcome), not their token. See room.py
    and match.py. Players' own state messages also
    have "you": [x speed, y speed, standing] for predicting their ball.
    "results" has "summaries" (how each slot did), "match_id" and "at",
    which browsers add to their match history (profiles.py).

On SIGTERM the server stops taking connections, lets the matches being
played finish (up to BONK_DRAIN_SECONDS), then sends every room "restart"
and closes. Browsers reconnect to the new server and reopen their room.
"""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
import traceback

from aiohttp import WSCloseCode, WSMsgType, web

from bonk_game.envs.utils.maps import MAPS, agent_dir
from bonk_game.server import auth, badges, limits, lobby, metrics, moderation, modes, playtest
from bonk_game.server.room import PasswordNeeded, RoomFull, RoomManager, ServerBusy, ServerFull, valid_code

STATIC = os.path.join(os.path.dirname(__file__), "static")
AGENT_KINDS = ("ppo", "a2c", "dqn", "ars", "bad")
SWEEP_EVERY = 5.0

ROOMS = web.AppKey("rooms", object)
ROOM_LIMIT = web.AppKey("room_limit", object)
GUESS_LIMIT = web.AppKey("guess_limit", object)
# Wrong room passwords one IP may try (a burst, then this many a minute)
WRONG_PASSWORDS = 10
CONNECTIONS = web.AppKey("connections", dict)
SWEEPER = web.AppKey("sweeper", object)
SOCKETS = web.AppKey("sockets", object)
MAX_MESSAGE = 4096
# Bump when a message changes in a way an old page can't handle. (Any change
# to the client files changes VERSION anyway.)
PROTOCOL = 1
DRAIN_SECONDS = limits._env("BONK_DRAIN_SECONDS", 120.0)
METRICS_TOKEN = os.environ.get("BONK_METRICS_TOKEN", "")
# Wrong metrics tokens one IP may try (a burst, then this many a minute)
WRONG_TOKENS = 10
TOKEN_LIMIT = web.AppKey("token_limit", object)
# The server's numbers every minute (metrics.History): a file, so they
# outlast restarts and deploys; ":memory:" (the default) keeps them only
# while the server runs
METRICS_DB = os.environ.get("BONK_METRICS_DB", ":memory:")
HISTORY = web.AppKey("history", object)
# Who comes back (metrics.Retention), in the same database as HISTORY
RETENTION = web.AppKey("retention", object)
SAMPLER = web.AppKey("sampler", object)
ADMIN = os.path.join(os.path.dirname(__file__), "admin")
# The admin page is nobody else's business: no search engines, no other
# site framing it, no address sent on when you follow a link
ADMIN_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self'; "
                                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                                "base-uri 'none'; form-action 'none'"),
}
# Proving to Google that you own the site (Search Console's "HTML tag"
# method: the content="..." part), which Google asks for before showing
# the app's name on its sign-in screen
SITE_VERIFICATION = os.environ.get("BONK_GOOGLE_SITE_VERIFICATION", "")
# How people reach whoever runs the server (an email address), for the
# privacy page
CONTACT = os.environ.get("BONK_CONTACT", "")


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
    # Map and mode names, for your match history on the home screen, and
    # the badges (badges.py) your stats earn
    names = json.dumps({"maps": {n: MAPS[n].title for n in MAPS},
                        "modes": {m["id"]: m["title"] for m in modes.describe_modes()},
                        "badges": badges.describe()})
    names = names.replace("<", "\\u003c")
    head = (f'<head>\n  <meta name="bonk-version" content="{version}">'
            f'\n  <script id="bonk-names" type="application/json">{names}</script>')
    if SITE_VERIFICATION:
        head += f'\n  <meta name="google-site-verification" content="{html.escape(SITE_VERIFICATION)}">'
    return page.replace("<head>", head, 1)


def render_privacy(contact=None, name="privacy.html"):
    """privacy.html (or terms.html), with how to reach whoever runs the server."""
    contact = CONTACT if contact is None else contact
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        page = f.read()
    if contact:
        safe = html.escape(contact)
        how = f'email <a href="mailto:{safe}">{safe}</a>' if "@" in contact else safe
    else:
        how = "contact whoever runs this server"
    return page.replace("{{contact}}", how)


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
PRIVACY_PAGE = web.AppKey("privacy_page", str)
TERMS_PAGE = web.AppKey("terms_page", str)


async def index(request):
    return web.Response(text=request.app[PAGE], content_type="text/html",
                        headers={"Cache-Control": "no-cache"})


# Every response: no guessing content types, no other site framing ours
# (clickjacking), no full addresses sent to other sites, HTTPS only from
# now on (once a browser has been here over HTTPS)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
HSTS = "max-age=31536000"
# The game's pages run only this site's own scripts and talk only to this
# site, so injected markup couldn't run code or send anything elsewhere.
# (wss: for browsers whose 'self' doesn't cover WebSockets yet)
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self' wss:; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def _https(request):
    if request.scheme == "https":
        return True
    return limits.TRUST_PROXY and request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() == "https"


@web.middleware
async def security_headers(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as e:
        response = e
        _add_security_headers(request, response)
        raise
    _add_security_headers(request, response)
    return response


def _add_security_headers(request, response):
    h = response.headers
    for k, v in SECURITY_HEADERS.items():
        h.setdefault(k, v)
    if _https(request):
        h.setdefault("Strict-Transport-Security", HSTS)
    if (response.content_type or "").startswith("text/html"):
        h.setdefault("Content-Security-Policy", PAGE_CSP)


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


def busy_response():
    """The server can't take anyone new right now: the page shows "busy" and
    tries again by itself in a few seconds."""
    return web.json_response({"error": "The servers are busy right now.", "busy": True,
                              "retry": limits.BUSY_RETRY},
                             status=503, headers={"Retry-After": str(limits.BUSY_RETRY)})


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
        return busy_response()
    # Every room is listed; it gets a password unless {"password": false}
    # (the host can change both in the lobby)
    try:
        body = await request.json() if request.can_read_body else {}
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    room.settings["name"] = lobby.clean_room_name(body.get("name")) if isinstance(body.get("name"), str) else None
    room.settings["password"] = None if body.get("password") is False else lobby.new_password()
    return web.json_response({"room": room.code, "name": room.settings["name"],
                              "password": room.settings["password"]})


async def public_rooms(request):
    """The game browser's list: {"rooms": [...], "online", "private", "more"}
    (RoomManager.browse)."""
    return web.json_response(request.app[ROOMS].browse(),
                             headers={"Cache-Control": "no-store"})


async def quick_play(request):
    """The public room to join, or a new one with bots."""
    rooms = request.app[ROOMS]
    if rooms.draining:
        return web.json_response({"error": "The server is restarting. Try again in a moment."}, status=503)
    ip = limits.client_ip(request)
    try:
        room, new = rooms.quick_play(allow_new=lambda: request.app[ROOM_LIMIT].allow(ip))
    except ServerFull:
        return busy_response()
    if room is None:
        return web.json_response({"error": "You're making rooms too quickly. Try again in a minute."},
                                 status=429)
    return web.json_response({"room": room.code, "new": new})


def _friends_user(request, change=False):
    """(accounts, the signed-in user) for the friends API, or an error."""
    accounts = request.app.get(auth.ACCOUNTS)
    if accounts is None:
        raise web.HTTPNotFound(text="Sign-in is off on this server")
    if change and not auth.same_origin(request):
        raise web.HTTPForbidden(text="Cross-site request")
    user = auth.user_for(request)
    if user is None:
        raise web.HTTPUnauthorized(text="Not signed in")
    return accounts, user


async def friends_list(request):
    """Your friends ({id, name, ball, online, where}: where they're playing,
    if they are), and the friend requests waiting either way."""
    accounts, user = _friends_user(request)
    out = accounts.friends(user["id"])
    where = request.app[ROOMS].where({f["id"] for f in out["friends"]})
    for f in out["friends"]:
        f["where"] = where.get(f["id"])
        f["online"] = f["where"] is not None
    out["friends"].sort(key=lambda f: (not f["online"], f["name"].lower()))
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def friend_accept(request):
    """Say yes to a friend request (only one that's waiting for you: a new
    request is made in a room, from the person's card)."""
    accounts, user = _friends_user(request, change=True)
    other = request.match_info["id"]
    if not any(r["id"] == other for r in accounts.friends(user["id"])["incoming"]):
        raise web.HTTPNotFound(text="No such friend request")
    result = accounts.befriend(user["id"], other)
    if result == "friends":
        name = (accounts.profile(user["id"]) or {}).get("name") or "Someone"
        await request.app[ROOMS].tell_account(other, {"type": "notice", "friends": "friends",
                                                      "message": f"You and {name} are friends now!"})
    return web.json_response({"result": result})


async def friend_remove(request):
    """Unfriend, turn down a request, or take yours back."""
    accounts, user = _friends_user(request, change=True)
    accounts.unfriend(user["id"], request.match_info["id"])
    return web.json_response({"ok": True})


async def room_info(request):
    room = request.app[ROOMS].get(request.match_info["code"])
    if room is None:
        raise web.HTTPNotFound(text="No such room")
    return web.json_response({"room": room.code, "players": len(room.connected),
                              "locked": bool(room.settings.get("password"))})


async def healthz(request):
    return web.Response(text="ok")


def _check_token(request, required=False):
    """The metrics token, as "Authorization: Bearer <token>". Without
    BONK_METRICS_TOKEN set, anyone may look (handy locally), unless
    `required`. An IP that keeps guessing wrong has to wait."""
    if not METRICS_TOKEN:
        if required:
            raise web.HTTPServiceUnavailable(text="Set BONK_METRICS_TOKEN on the server first.",
                                             headers=ADMIN_HEADERS)
        return
    given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), METRICS_TOKEN.encode()):
        if not request.app[TOKEN_LIMIT].allow(limits.client_ip(request)):
            raise web.HTTPTooManyRequests(text="Too many wrong tokens. Try again in a minute.",
                                          headers=ADMIN_HEADERS)
        metrics.event("wrong_metrics_token", logging.WARNING, path=request.path)
        raise web.HTTPUnauthorized(text="Send the metrics token.", headers=ADMIN_HEADERS)


async def playtest_page(request):
    """The latest playtest reports and browser errors (playtest.py)."""
    _check_token(request)
    return web.json_response({"version": VERSION, "items": list(playtest.REPORTS.items)},
                             headers={"Cache-Control": "no-store"})


async def reports_page(request):
    """The latest player reports (moderation.py)."""
    _check_token(request)
    return web.json_response({"total": moderation.REPORTS.total, "items": list(moderation.REPORTS.items)},
                             headers={"Cache-Control": "no-store"})


def _snapshot(app):
    """Everything /metrics reports."""
    snap = metrics.STATS.snapshot(app[ROOMS])
    snap["playtest_reports_total"] = playtest.REPORTS.reports
    snap["client_errors_total"] = playtest.REPORTS.client_errors
    snap["player_reports_total"] = moderation.REPORTS.total
    snap["version"] = VERSION
    return snap


async def metrics_page(request):
    _check_token(request)
    snap = _snapshot(request.app)
    headers = {"Cache-Control": "no-store"}
    if request.query.get("format") == "json":
        return web.json_response(snap, headers=headers)
    snap.pop("version")
    text = f'# TYPE bonk_info gauge\nbonk_info{{version="{VERSION}"}} 1\n' + metrics.prometheus(snap)
    return web.Response(text=text, content_type="text/plain", headers=headers)


ADMIN_FILES = {"admin.js": "application/javascript", "admin.css": "text/css"}
ADMIN_RANGES = (3600, 6 * 3600, 86400, 7 * 86400, 30 * 86400, 90 * 86400)


async def admin_page(request):
    """The page itself has no secrets in it: the numbers come from
    /api/admin/metrics, which needs the token."""
    name = request.match_info.get("file", "admin.html")
    if name != "admin.html" and name not in ADMIN_FILES:
        raise web.HTTPNotFound()
    with open(os.path.join(ADMIN, name), encoding="utf-8") as f:
        text = f.read()
    return web.Response(text=text, content_type=ADMIN_FILES.get(name, "text/html"),
                        headers=ADMIN_HEADERS)


async def admin_metrics(request):
    _check_token(request, required=True)
    try:
        seconds = int(request.query.get("range", 86400))
    except ValueError:
        seconds = 86400
    seconds = min(ADMIN_RANGES, key=lambda r: abs(r - seconds))
    history = request.app[HISTORY]
    return web.json_response({
        "now": _snapshot(request.app),
        "range": seconds,
        "sample_every": history.SAMPLE_EVERY,
        "keep_days": history.KEEP_DAYS,
        "kept": history.path != ":memory:",
        "history": history.series(seconds),
        "retention": request.app[RETENTION].report(),
        "regions": history.regions(seconds),
    }, headers=ADMIN_HEADERS)


async def websocket(request):
    rooms = request.app[ROOMS]
    conns = request.app[CONNECTIONS]
    ip = limits.client_ip(request)
    # compress: permessage-deflate, if the browser asks (they do). Costs CPU
    # per connection; BONK_WS_COMPRESS=0 trades it for more bandwidth.
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MESSAGE, compress=limits.WS_COMPRESS)
    await ws.prepare(request)
    metrics.STATS.count_wire(request.transport)
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
                    # It keeps the password whoever's first back had
                    room.settings["password"] = lobby.clean_password(msg.get("password"))
                except ServerFull:
                    pass
        if room is None:
            return await refuse("That room doesn't exist (or has closed).")
        token = str(msg.get("token") or "")[:64] or secrets.token_hex(12)
        # Signed in? (The cookie comes with the WebSocket; only this site's
        # own pages count, so another site can't play as you)
        user = auth.user_for(request) if auth.same_origin(request) else None
        password = msg.get("password") if isinstance(msg.get("password"), str) else None
        if password and not room.password_ok(token, password) and not request.app[GUESS_LIMIT].allow(ip):
            return await refuse("Too many wrong passwords. Try again in a minute.")
        try:
            member = await room.join(token, msg.get("name"), send, was_host=msg.get("host") is True,
                                     account=user["id"] if user else None, password=password,
                                     watch=msg.get("watch") is True)
            member.region = limits.client_region(request)
            tz = msg.get("tz")  # (their clock, for time-of-day badges: badges.py)
            member.tz = tz if isinstance(tz, int) and not isinstance(tz, bool) and -840 <= tz <= 840 else None
        except PasswordNeeded as e:
            token = None
            return await refuse(str(e), password=True, wrong=e.wrong)
        except ServerBusy as e:
            token = None
            return await refuse(str(e), busy=True, retry=limits.BUSY_RETRY)
        except RoomFull as e:
            token = None
            return await refuse(str(e))
        try:  # for retention on /admin; never stops anyone playing
            request.app[RETENTION].seen(token, installed=msg.get("installed") is True)
        except Exception as e:
            metrics.event("error", logging.ERROR, where="retention", error=repr(e))

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
    n = 0
    while True:
        await asyncio.sleep(SWEEP_EVERY)
        await app[ROOMS].sweep()
        n += 1
        if n % 720 == 0 and app.get(auth.ACCOUNTS) is not None:  # hourly
            app[auth.ACCOUNTS].sweep()


async def _sampler(app):
    """A sample for the history every minute (and one now, so a fresh
    server shows up straight away)."""
    history = app[HISTORY]
    n = 0
    while True:
        try:
            history.add(_snapshot(app))
            if n % 60 == 0:  # hourly
                history.prune()
                app[RETENTION].prune()
        except Exception as e:  # (a full disk, say): the game carries on
            metrics.event("error", logging.ERROR, where="metrics_history", error=repr(e))
        n += 1
        await asyncio.sleep(history.SAMPLE_EVERY)


async def _start_background(app):
    app[SWEEPER] = asyncio.ensure_future(_sweeper(app))
    app[SAMPLER] = asyncio.ensure_future(_sampler(app))


async def _shutdown(app, drain=None):
    """SIGTERM: the listening socket is already closed (no new connections).
    Let matches finish, tell everyone, and close the WebSockets."""
    await app[ROOMS].drain(DRAIN_SECONDS if drain is None else drain)
    for ws in list(app[SOCKETS]):
        await ws.close(code=WSCloseCode.SERVICE_RESTART, message=b"server restarting")


async def _stop_background(app):
    app[SWEEPER].cancel()
    app[SAMPLER].cancel()
    try:
        app[HISTORY].add(_snapshot(app))  # the last numbers before stopping
    except Exception:
        pass
    for room in list(app[ROOMS].rooms.values()):
        await room.stop()


async def manifest(request):
    """The web app's manifest (Add to Home Screen): served from the root so
    its scope is the whole site, with the right content type."""
    with open(os.path.join(STATIC, "manifest.webmanifest"), encoding="utf-8") as f:
        text = f.read()
    return web.Response(text=text, content_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


async def privacy(request):
    return web.Response(text=request.app[PRIVACY_PAGE], content_type="text/html",
                        headers={"Cache-Control": "no-cache"})


async def terms(request):
    return web.Response(text=request.app[TERMS_PAGE], content_type="text/html",
                        headers={"Cache-Control": "no-cache"})


def make_app(rooms=None, auth_config=None, accounts=None, history=None):
    """auth_config, accounts, history: for tests (normally from the
    environment: auth.Config, BONK_METRICS_DB)."""
    app = web.Application(middlewares=[security_headers, cache_headers])
    app[ROOMS] = rooms or RoomManager(AgentStore())
    app[ROOM_LIMIT] = limits.PerKey(limits.ROOMS_PER_IP / 60, limits.ROOMS_PER_IP)
    app[GUESS_LIMIT] = limits.PerKey(WRONG_PASSWORDS / 60, WRONG_PASSWORDS)
    app[TOKEN_LIMIT] = limits.PerKey(WRONG_TOKENS / 60, WRONG_TOKENS)
    app[HISTORY] = history or metrics.History(METRICS_DB)
    app[RETENTION] = metrics.Retention(app[HISTORY].db, clock=app[HISTORY].clock)
    app[CONNECTIONS] = {}  # ip -> open WebSockets
    app[SOCKETS] = set()  # open WebSockets, closed on shutdown
    app[PAGE] = render_index()
    app[PRIVACY_PAGE] = render_privacy()
    app[TERMS_PAGE] = render_privacy(name="terms.html")
    app.router.add_get("/", index)
    app.router.add_get("/r/{code}", index)
    app.router.add_get("/play", index)        # the game browser
    app.router.add_get("/leaderboard", index)  # the leaderboard
    app.router.add_post("/api/rooms", create_room)
    app.router.add_get("/api/public", public_rooms)
    app.router.add_post("/api/quickplay", quick_play)
    app.router.add_get("/api/reports", reports_page)
    app.router.add_get("/api/rooms/{code}", room_info)
    app.router.add_get("/api/friends", friends_list)
    app.router.add_post("/api/friends/{id}", friend_accept)
    app.router.add_delete("/api/friends/{id}", friend_remove)
    app.router.add_get("/ws/{code}", websocket)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/metrics", metrics_page)
    app.router.add_get("/api/playtest", playtest_page)
    app.router.add_get("/admin", admin_page)
    app.router.add_get("/admin/{file}", admin_page)
    app.router.add_get("/api/admin/metrics", admin_metrics)
    app.router.add_get("/manifest.webmanifest", manifest)
    app.router.add_get("/privacy", privacy)
    app.router.add_get("/terms", terms)
    accounts = auth.setup(app, auth_config, accounts)
    if accounts is not None and app[ROOMS].recorder is None:
        app[ROOMS].recorder = accounts.record  # signed-in players' match history
    if accounts is not None and app[ROOMS].profile_of is None:
        app[ROOMS].profile_of = accounts.profile  # what they've unlocked (cosmetics.py)
    if accounts is not None and app[ROOMS].ratings is None:
        app[ROOMS].ratings = accounts  # signed-in players' ratings (rating.py)
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
