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
                                  "profile": {...}, (signed in only)
                                  "cosmetics": {...}} (what you can wear:
                                  cosmetics.catalog)
    PUT  /api/me/profile         change your name, ball or settings
    POST /api/me/merge           add a browser's profile (first sign-in) to
                                 your account: done once when you sign in
    DELETE /api/me               delete your account

How sign-in works (OpenID Connect's "authorization code" flow, with PKCE),
done by Authlib (https://authlib.org): the browser goes to Google with a
random `state`, a `nonce` and a PKCE code challenge, kept for the way back
in a short-lived cookie. Google sends it back with a code, which Authlib's
OAuth client swaps (with our client secret and the PKCE verifier) for
Google's ID token. joserfc (Authlib's JOSE library) checks the token is
signed by one of Google's published keys, and its claims are from Google,
for this client, current and for this sign-in (the nonce). They say who
signed in ("sub", their email and name). Then the server starts a session:
a random cookie (HttpOnly, SameSite=Lax, Secure over HTTPS) whose hash is
in the database (accounts.py), so signing out or deleting the account ends
it everywhere.

Changes (PUT, POST, DELETE) must come from this site's own pages: the
cookie is SameSite=Lax, and the Origin header has to match.
"""
import base64
import json
import os
import re
import secrets
import time

import httpx2
from aiohttp import web
from authlib.common.errors import AuthlibBaseError
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from bonk_game.server import cosmetics, limits, metrics, rating
from bonk_game.server.accounts import SESSION_DAYS, Accounts

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_KEYS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
SCOPE = "openid email profile"
CLOCK_SKEW = 60  # seconds of difference between our clock and Google's that's fine
SESSION_COOKIE = "bonk_session"
FLOW_COOKIE = "bonk_signin"
FLOW_SECONDS = 600
MAX_BODY = 256 * 1024   # a profile is a few KB

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


def oauth_client(cfg, redirect_uri, transport=None):
    """Authlib's OAuth 2 client for Google, with PKCE (S256)."""
    return AsyncOAuth2Client(cfg.client_id, cfg.client_secret, scope=SCOPE, redirect_uri=redirect_uri,
                             code_challenge_method="S256", timeout=10, transport=transport)


def _max_age(cache_control, default):
    m = re.search(r"max-age=(\d+)", cache_control or "")
    return int(m.group(1)) if m else default


class GoogleKeys:
    """Google's public keys, for checking ID tokens' signatures. Fetched when
    first needed and kept as long as Google says (Cache-Control); fetched
    again early if a token names a key we don't have (Google rotates them)."""

    def __init__(self, url=GOOGLE_KEYS_URL):
        self.url = url
        self.keys = None
        self.until = 0.0

    async def get(self, refresh=False, transport=None):
        if refresh or self.keys is None or time.time() >= self.until:
            async with httpx2.AsyncClient(timeout=10, transport=transport) as http:
                r = await http.get(self.url)
                r.raise_for_status()
            self.keys = KeySet.import_key_set(r.json())
            self.until = time.time() + _max_age(r.headers.get("Cache-Control"), 3600)
        return self.keys


GOOGLE_KEYS = GoogleKeys()


def verify_id_token(id_token, keys, client_id, nonce, now=None):
    """The claims of Google's ID token if it's signed with one of `keys`,
    from Google, for `client_id`, current, and for this sign-in (`nonce`);
    else None."""
    try:
        token = jwt.decode(id_token, keys, algorithms=["RS256"])
        jwt.JWTClaimsRegistry(
            now=None if now is None else int(now), leeway=CLOCK_SKEW,
            iss={"essential": True, "values": GOOGLE_ISSUERS},
            aud={"essential": True, "value": client_id},
            sub={"essential": True},
            exp={"essential": True},
            nonce={"essential": True, "value": nonce},
        ).validate(token.claims)
    except (JoseError, ValueError, TypeError):
        return None
    return token.claims


def signed_in_as(claims):
    """Who checked claims say signed in: (sub, email, name), or None. The
    email only if Google has verified it."""
    if not isinstance(claims, dict):
        return None
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    email = claims.get("email") if claims.get("email_verified") is True else ""
    name = claims.get("given_name") or claims.get("name") or ""
    return sub, str(email or "")[:200], str(name)[:60]


async def exchange_code(cfg, code, redirect_uri, verifier, nonce, transport=None):
    """Google's checked ID token claims for a sign-in code, or None. (Tests
    replace this, or pass an httpx2 transport that pretends to be Google:
    it's the only part that talks to Google.)"""
    try:
        async with oauth_client(cfg, redirect_uri, transport) as client:
            token = await client.fetch_token(GOOGLE_TOKEN_URL, code=code, code_verifier=verifier)
        id_token = token.get("id_token", "")
        keys = await GOOGLE_KEYS.get(transport=transport)
        claims = verify_id_token(id_token, keys, cfg.client_id, nonce)
        if claims is None and _unknown_key(id_token, keys):
            keys = await GOOGLE_KEYS.get(refresh=True, transport=transport)
            claims = verify_id_token(id_token, keys, cfg.client_id, nonce)
    except (AuthlibBaseError, httpx2.HTTPError, ValueError) as e:
        metrics.event("signin_failed", why="token", error=type(e).__name__)
        return None
    if claims is None:
        metrics.event("signin_failed", why="id_token")
    return claims


def _unknown_key(id_token, keys):
    """Does the token name a key that isn't in `keys`? (Then Google may have
    rotated its keys since we fetched them.)"""
    try:
        raw = id_token.split(".")[0]
        header = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        return header.get("kid") not in {k.kid for k in keys.keys}
    except (ValueError, AttributeError, IndexError):
        return False


# --- routes -------------------------------------------------------------------
async def google_start(request):
    cfg = request.app[CONFIG]
    if not cfg.enabled:
        raise web.HTTPNotFound(text="Sign-in isn't set up on this server")
    verifier, nonce = generate_token(48), generate_token(24)
    client = oauth_client(cfg, _site(request) + "/auth/google/callback")
    url, state = client.create_authorization_url(GOOGLE_AUTH_URL, code_verifier=verifier, nonce=nonce,
                                                 prompt="select_account")
    response = web.HTTPFound(url)
    flow = json.dumps({"state": state, "verifier": verifier, "nonce": nonce,
                       "next": _safe_next(request.query.get("next"))})
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
                                 str(flow.get("verifier", "")), str(flow.get("nonce", "")))
    who = signed_in_as(claims)
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
    out["cosmetics"] = cosmetics.catalog(signed_in=user is not None)
    return out


async def me(request):
    return web.json_response(_me(request, user_for(request)), headers={"Cache-Control": "no-store"})


async def leaderboard(request):
    """The leaderboard (rating.py): the best 100 signed-in players, and, when
    you're signed in, your own rating and place ("you")."""
    accounts = request.app.get(ACCOUNTS)
    out = {"accounts": accounts is not None, "players": [], "total": 0, "you": None,
           "placement": rating.PLACEMENT}
    if accounts is not None:
        rows, out["total"] = accounts.leaderboard()
        user = user_for(request)
        for r in rows:
            account = r.pop("account")  # (never sent: only whether it's yours)
            r["you"] = user is not None and account == user["id"]
        out["players"] = rows
        if user is not None:
            out["you"] = accounts.rating(user["id"])
    return web.json_response(out, headers={"Cache-Control": "no-store"})


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
    app.router.add_get("/api/leaderboard", leaderboard)
    app.router.add_put("/api/me/profile", update_profile)
    app.router.add_post("/api/me/merge", merge_profile)
    app.router.add_delete("/api/me", delete_account)
    return accounts
