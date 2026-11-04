"""Signing in with Google, and the signed-in player's account (accounts.py).

Turned on by setting GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (from a
Google Cloud "OAuth client ID" of type "Web application", whose authorised
redirect URI is <site>/auth/google/callback). Without them the server runs
as before: everyone's a guest, and /api/me says accounts are off.

Routes:
    GET  /auth/google            off to Google's sign-in page (?next=/r/ABCD
                                 comes back to that page afterwards)
    GET  /auth/google/callback   Google sends people back here
    POST /auth/logout            sign out (this browser)
    GET  /api/me                 {"accounts": on?, "user": {...} or null,
                                  "profile": {...}} (profile: signed in only)
    PUT  /api/me/profile         change your name, ball or settings
    POST /api/me/merge           add a browser profile (or profile file) to
                                 your account: done once when you sign in
    DELETE /api/me               delete your account

How sign-in works (OpenID Connect's "authorization code" flow, with PKCE):
the browser goes to Google with a random `state` and a code challenge, both
also kept in a short-lived cookie. Google sends it back with a code, which
the server swaps (with its client secret) for Google's ID token, straight
from Google over HTTPS. Its claims say who signed in ("sub", their email
and name); the server checks they're for this client, from Google, and
current. Then it starts a session: a random cookie (HttpOnly, SameSite=Lax,
Secure over HTTPS) whose hash is in the database.

Changes (PUT, POST, DELETE) must come from this site's own pages: the
cookie is SameSite=Lax, and the Origin header has to match.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from bonk_game.server import limits, metrics
from bonk_game.server.accounts import SESSION_DAYS, Accounts

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SESSION_COOKIE = "bonk_session"
FLOW_COOKIE = "bonk_signin"
FLOW_SECONDS = 600
MAX_BODY = 256 * 1024   # a profile file is a few KB

ACCOUNTS = web.AppKey("accounts", object)
CONFIG = web.AppKey("auth_config", object)


class Config:
    """Where sign-in settings come from: the environment, unless given."""

    def __init__(self, client_id=None, client_secret=None, public_url=None, db=None):
        env = os.environ.get
        self.client_id = client_id if client_id is not None else env("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret if client_secret is not None else env("GOOGLE_CLIENT_SECRET", "")
        # The site's address, for Google's redirect (else worked out per request)
        self.public_url = (public_url if public_url is not None else env("BONK_PUBLIC_URL", "")).rstrip("/")
        self.db = db if db is not None else env("BONK_DB", "bonk.db")

    @property
    def enabled(self):
        return bool(self.client_id and self.client_secret)


# --- helpers ------------------------------------------------------------------
def _site(request):
    """https://host for this request (behind Fly's proxy, the original scheme)."""
    cfg = request.app[CONFIG]
    if cfg.public_url:
        return cfg.public_url
    scheme = request.scheme
    if limits.TRUST_PROXY:
        scheme = request.headers.get("X-Forwarded-Proto", scheme).split(",")[0].strip() or scheme
    return f"{scheme}://{request.host}"


def _secure(request):
    return _site(request).startswith("https://")


def _cookie(response, request, name, value, max_age):
    response.set_cookie(name, value, max_age=max_age, path="/", httponly=True,
                        samesite="Lax", secure=_secure(request))


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _safe_next(path):
    """Only come back to a page on this site (/... but not //elsewhere)."""
    if isinstance(path, str) and path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path[:200]
    return "/"


def user_for(request):
    """The signed-in account for a request (or WebSocket), or None."""
    accounts = request.app.get(ACCOUNTS)
    if accounts is None:
        return None
    return accounts.session_user(request.cookies.get(SESSION_COOKIE, ""))


def same_origin(request):
    origin = request.headers.get("Origin")
    return origin is not None and origin.rstrip("/") == _site(request)


async def _json_body(request):
    if request.content_length is not None and request.content_length > MAX_BODY:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=request.content_length)
    try:
        return json.loads(await request.text())
    except ValueError:
        raise web.HTTPBadRequest(text="Not JSON") from None


def _signed_in(request):
    """The account for a change request, or an error response."""
    if not same_origin(request):
        raise web.HTTPForbidden(text="Cross-site request")
    user = user_for(request)
    if user is None:
        raise web.HTTPUnauthorized(text="Not signed in")
    return user


def _decode_jwt_claims(token):
    """The claims of a JWT. Not checking the signature is fine here: the token
    came straight from Google's token endpoint over HTTPS, in answer to our
    client secret (OpenID Connect Core, 3.1.3.7)."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, AttributeError):
        return None


async def exchange_code(cfg, code, redirect_uri, verifier):
    """Google's ID token claims for a sign-in code, or None. (Tests replace
    this: it's the only part that talks to Google.)"""
    data = {"code": code, "client_id": cfg.client_id, "client_secret": cfg.client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier}
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(GOOGLE_TOKEN_URL, data=data) as r:
            if r.status != 200:
                metrics.event("signin_failed", why="token", status=r.status)
                return None
            body = await r.json()
    return _decode_jwt_claims(body.get("id_token", ""))


def check_claims(claims, client_id, now=None):
    """Who signed in, if Google's claims are for us and current: (sub, email,
    name), else None."""
    now = time.time() if now is None else now
    if not isinstance(claims, dict):
        return None
    if claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != client_id:
        return None
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < now:
        return None
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    email = claims.get("email") if claims.get("email_verified") is True else ""
    name = claims.get("given_name") or claims.get("name") or ""
    return sub, str(email or "")[:200], str(name)[:60]


# --- routes -------------------------------------------------------------------
async def google_start(request):
    cfg = request.app[CONFIG]
    if not cfg.enabled:
        raise web.HTTPNotFound(text="Sign-in isn't set up on this server")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    params = {"client_id": cfg.client_id, "redirect_uri": _site(request) + "/auth/google/callback",
              "response_type": "code", "scope": "openid email profile", "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"}
    response = web.HTTPFound(GOOGLE_AUTH_URL + "?" + urlencode(params))
    flow = json.dumps({"state": state, "verifier": verifier, "next": _safe_next(request.query.get("next"))})
    _cookie(response, request, FLOW_COOKIE, _b64(flow.encode()), FLOW_SECONDS)
    raise response


async def google_callback(request):
    cfg = request.app[CONFIG]
    if not cfg.enabled:
        raise web.HTTPNotFound(text="Sign-in isn't set up on this server")
    try:
        raw = request.cookies.get(FLOW_COOKIE, "")
        flow = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except ValueError:
        flow = None

    def back(problem):
        # Home, with a message for the page to show
        response = web.HTTPFound("/?signin=" + problem)
        response.del_cookie(FLOW_COOKIE, path="/")
        return response

    if not isinstance(flow, dict) or not secrets.compare_digest(str(flow.get("state", "")),
                                                                request.query.get("state", "")):
        raise back("expired")
    if "error" in request.query or "code" not in request.query:
        raise back("cancelled")
    claims = await exchange_code(cfg, request.query["code"], _site(request) + "/auth/google/callback",
                                 str(flow.get("verifier", "")))
    who = check_claims(claims, cfg.client_id)
    if who is None:
        metrics.event("signin_failed", why="claims")
        raise back("failed")
    accounts = request.app[ACCOUNTS]
    user, new = accounts.sign_in(*who)
    metrics.event("signed_in", user=user["id"], new=new)
    response = web.HTTPFound(_safe_next(flow.get("next")))
    response.del_cookie(FLOW_COOKIE, path="/")
    _cookie(response, request, SESSION_COOKIE, accounts.new_session(user["id"]), SESSION_DAYS * 86400)
    raise response


async def logout(request):
    if not same_origin(request):
        raise web.HTTPForbidden(text="Cross-site request")
    accounts = request.app.get(ACCOUNTS)
    if accounts is not None:
        accounts.end_session(request.cookies.get(SESSION_COOKIE, ""))
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE, path="/")
    return response


def _me(request, user):
    accounts = request.app.get(ACCOUNTS)
    out = {"accounts": accounts is not None, "user": None}
    if user is not None:
        out["user"] = {"id": user["id"], "name": user["name"], "email": user["email"]}
        out["profile"] = accounts.profile(user["id"])
    return out


async def me(request):
    return web.json_response(_me(request, user_for(request)), headers={"Cache-Control": "no-store"})


async def update_profile(request):
    user = _signed_in(request)
    body = await _json_body(request)
    request.app[ACCOUNTS].update(user["id"], body)
    return web.json_response(_me(request, user))


async def merge_profile(request):
    user = _signed_in(request)
    body = await _json_body(request)
    before = request.app[ACCOUNTS].profile(user["id"])["stats"]["matches"]
    after = request.app[ACCOUNTS].merge(user["id"], body)
    out = _me(request, user)
    out["added"] = after["stats"]["matches"] - before
    return web.json_response(out)


async def delete_account(request):
    user = _signed_in(request)
    request.app[ACCOUNTS].delete(user["id"])
    metrics.event("account_deleted", user=user["id"])
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE, path="/")
    return response


def setup(app, config=None, accounts=None):
    """Add sign-in to the app. Accounts are on only when Google's client id
    and secret are set (or `accounts` is given, for tests)."""
    cfg = config or Config()
    app[CONFIG] = cfg
    if accounts is None and cfg.enabled:
        accounts = Accounts(cfg.db)
        metrics.event("accounts_on", db=cfg.db, users=accounts.count())
    if accounts is not None:
        app[ACCOUNTS] = accounts
    app.router.add_get("/auth/google", google_start)
    app.router.add_get("/auth/google/callback", google_callback)
    app.router.add_post("/auth/logout", logout)
    app.router.add_get("/api/me", me)
    app.router.add_put("/api/me/profile", update_profile)
    app.router.add_post("/api/me/merge", merge_profile)
    app.router.add_delete("/api/me", delete_account)
    return accounts
