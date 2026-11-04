"""Accounts (accounts.py) and signing in with Google (auth.py), issue #38.

Google's side is faked: auth.exchange_code is the only part that talks to
Google. Most tests replace it with claims like Google's; one runs it against
a pretend Google (an httpx2 transport) with ID tokens signed by a test key.
"""
import asyncio
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

aiohttp = pytest.importorskip("aiohttp")  # (the web server's packages; the training CI job has none)
httpx = pytest.importorskip("httpx2")
from joserfc import jwt  # noqa: E402
from joserfc.jwk import KeySet, RSAKey  # noqa: E402

from bonk_game.server import auth, profiles  # noqa: E402
from bonk_game.server.accounts import SESSION_DAYS, Accounts  # noqa: E402
from bonk_game.server.web import ROOMS as ROOMS_KEY  # noqa: E402
from bonk_game.server.web import VERSION, make_app  # noqa: E402

CLIENT = "client-123.apps.googleusercontent.com"


def run(coro):
    return asyncio.run(coro)


def claims(sub="g-1", **extra):
    return {"iss": "https://accounts.google.com", "aud": CLIENT, "exp": time.time() + 600, "sub": sub,
            "email": "sam@example.com", "email_verified": True, "given_name": "Sam", **extra}


def guest_profile(matches=2, pid="browser-1"):
    p = profiles.empty(pid)
    p["name"], p["color"], p["pattern"], p["prefs"] = "Sammy", 4, "dots", {"volume": 0.3}
    for k in range(matches):
        p = profiles.record(p, {"id": f"m{k}", "at": 1_700_000_000 + k, "mode": "ffa", "map": "platform",
                                "place": 1, "of": 2, "won": True, "score": 5, "kos": 1, "falls": 0,
                                "deaths": 0, "best_hit": 3.0, "pickups": 0, "awards": [], "players": 2,
                                "people": 1})
    return p


# --- the store ------------------------------------------------------------------
def test_sign_in_makes_an_account_once():
    a = Accounts(":memory:")
    u, new = a.sign_in("g-1", "sam@example.com", "Sam")
    assert new and u["email"] == "sam@example.com" and a.profile(u["id"])["name"] == "Sam"
    again, new = a.sign_in("g-1", "sam@new.example", "Sam")
    assert not new and again["id"] == u["id"] and again["email"] == "sam@new.example"
    assert a.count() == 1


def test_sessions_end_when_they_run_out_or_sign_out():
    now = [1_000_000.0]
    a = Accounts(":memory:", clock=lambda: now[0])
    u, _ = a.sign_in("g-1")
    t = a.new_session(u["id"])
    assert a.session_user(t)["id"] == u["id"]
    assert a.session_user("nope") is None and a.session_user("") is None
    # Only a hash is stored
    assert t not in json.dumps([tuple(r) for r in a.db.execute("SELECT * FROM sessions")])
    now[0] += SESSION_DAYS * 86400 + 1
    assert a.session_user(t) is None
    t2 = a.new_session(u["id"])
    a.end_session(t2)
    assert a.session_user(t2) is None


def test_merging_a_browser_profile_counts_once_and_a_new_account_takes_its_ball():
    a = Accounts(":memory:")
    u, _ = a.sign_in("g-1", name="Sam")
    p = a.merge(u["id"], guest_profile(2))
    assert p["stats"]["matches"] == 2 and p["name"] == "Sammy" and p["color"] == 4 and p["pattern"] == "dots"
    assert a.merge(u["id"], guest_profile(2))["stats"]["matches"] == 2  # same browser again
    # A second browser adds to it, but doesn't take over the name and ball
    other = {**guest_profile(1, "browser-2"), "name": "Other", "color": 1}
    other["history"][0]["id"] = "elsewhere"
    p = a.merge(u["id"], other)
    assert p["stats"]["matches"] == 3 and p["name"] == "Sammy"
    assert a.merge(u["id"], {"format": "nope"})["stats"]["matches"] == 3


def test_browsers_change_name_ball_and_settings_but_not_stats():
    a = Accounts(":memory:")
    u, _ = a.sign_in("g-1")
    p = a.update(u["id"], {"name": "  New  ", "color": 2, "prefs": {"shake": False},
                           "stats": {"matches": 999}, "history": [{"id": "fake"}]})
    assert p["name"] == "  New  "[:16] and p["color"] == 2 and p["prefs"] == {"shake": False}
    assert p["stats"]["matches"] == 0 and p["history"] == []
    assert a.update(u["id"], {"color": 99})["color"] is None  # (not a colour: none)


def test_matches_are_recorded_and_deleting_removes_everything():
    a = Accounts(":memory:")
    u, _ = a.sign_in("g-1")
    entry = guest_profile(1)["history"][0]
    a.record(u["id"], entry)
    a.record(u["id"], entry)  # the same match twice counts once
    assert a.profile(u["id"])["stats"]["matches"] == 1
    t = a.new_session(u["id"])
    a.delete(u["id"])
    assert a.user(u["id"]) is None and a.profile(u["id"]) is None and a.session_user(t) is None


GOOGLE_KEY = RSAKey.generate_key(2048, parameters={"kid": "google-1"})
PUBLIC_KEYS = KeySet([GOOGLE_KEY]).as_dict(private=False)


def id_token(key=GOOGLE_KEY, kid="google-1", **extra):
    """An ID token like Google's, signed with `key`."""
    body = {"iat": int(time.time()), "nonce": "n-1", **claims(**extra)}
    body["exp"] = int(body["exp"])
    return jwt.encode({"alg": "RS256", "kid": kid}, body, key)


def test_google_id_tokens_are_checked():
    keys = KeySet.import_key_set(PUBLIC_KEYS)
    check = lambda token, nonce="n-1": auth.verify_id_token(token, keys, CLIENT, nonce)  # noqa: E731
    assert auth.signed_in_as(check(id_token())) == ("g-1", "sam@example.com", "Sam")
    assert check(id_token(aud="someone-else")) is None
    assert check(id_token(iss="https://evil.example")) is None
    assert check(id_token(exp=int(time.time()) - 3600)) is None
    assert check(id_token(), nonce="another sign-in") is None
    # Signed by someone other than Google, or not a token at all
    assert check(id_token(key=RSAKey.generate_key(2048, parameters={"kid": "google-1"}))) is None
    assert check("garbage") is None
    assert auth.signed_in_as(check(id_token(sub=""))) is None
    assert auth.signed_in_as(check(id_token(email_verified=False)))[1] == ""
    assert auth.signed_in_as(None) is None


def pretend_google(seen, kid="google-1", key=GOOGLE_KEY):
    """An httpx2 transport that answers like Google's token endpoint and key list."""
    def handler(request):
        if request.url == auth.GOOGLE_TOKEN_URL:
            seen["form"] = parse_qs(request.content.decode())
            if seen["form"].get("code") != ["good"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "a", "token_type": "Bearer", "expires_in": 3600,
                                             "id_token": id_token(key=key, kid=kid)})
        if request.url == auth.GOOGLE_KEYS_URL:
            seen["keys"] = seen.get("keys", 0) + 1
            return httpx.Response(200, json=PUBLIC_KEYS, headers={"Cache-Control": "public, max-age=600"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_the_code_is_swapped_for_a_checked_id_token(monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_KEYS", auth.GoogleKeys())
    cfg = auth.Config(client_id=CLIENT, client_secret="secret", db=":memory:")
    seen = {}
    claims_ = run(auth.exchange_code(cfg, "good", "https://bonk.example/auth/google/callback", "v" * 48, "n-1",
                                     transport=pretend_google(seen)))
    assert auth.signed_in_as(claims_) == ("g-1", "sam@example.com", "Sam")
    # PKCE: the verifier goes with the code, and so do our client's details
    assert seen["form"]["code_verifier"] == ["v" * 48]
    assert seen["form"]["redirect_uri"] == ["https://bonk.example/auth/google/callback"]
    assert seen["keys"] == 1
    # A code Google won't swap, or a token for another sign-in, signs nobody in
    assert run(auth.exchange_code(cfg, "bad", "https://x/cb", "v" * 48, "n-1", transport=pretend_google(seen))) is None
    assert run(auth.exchange_code(cfg, "good", "https://x/cb", "v" * 48, "n-2", transport=pretend_google(seen))) is None
    # Google's keys are kept, and fetched again for a key we haven't seen
    assert seen["keys"] == 1
    other = RSAKey.generate_key(2048, parameters={"kid": "google-2"})
    assert run(auth.exchange_code(cfg, "good", "https://x/cb", "v" * 48, "n-1",
                                  transport=pretend_google(seen, "google-2", other))) is None
    assert seen["keys"] == 2


def test_only_pages_on_this_site_are_come_back_to():
    assert auth._safe_next("/r/ABCD") == "/r/ABCD"
    for bad in ("//evil.example", "https://evil.example", "/\\evil", None, ""):
        assert auth._safe_next(bad) == "/"


# --- over HTTP ------------------------------------------------------------------
def test_accounts_are_off_without_google_settings():
    from aiohttp.test_utils import TestClient, TestServer

    async def go():
        app = make_app(auth_config=auth.Config(client_id="", client_secret="", db=":memory:"))
        async with TestClient(TestServer(app)) as client:
            r = await client.get("/api/me")
            body = await r.json()
            assert body["accounts"] is False and body["user"] is None
            # A guest can wear everything but the members' few
            free = {i["id"] for i in body["cosmetics"]["pattern"] if i["unlocked"]}
            assert {"plain", "swirl", "target", "flame"} <= free and "galaxy" not in free
            r = await client.get("/auth/google", allow_redirects=False)
            assert r.status == 404
            r = await client.get("/privacy")
            assert r.status == 200 and "Google" in await r.text()
            r = await client.get("/terms")
            assert r.status == 200 and "Terms of service" in await r.text()
    run(go())


def test_sign_in_play_and_delete(monkeypatch):
    """The whole flow: sign in, bring a browser profile along, play a match
    (the server records it), change your ball, sign out, delete."""
    from aiohttp.test_utils import TestClient, TestServer
    accounts = Accounts(":memory:")
    seen = {}

    async def fake_exchange(cfg, code, redirect_uri, verifier, nonce):
        seen.update(code=code, redirect_uri=redirect_uri, verifier=verifier, nonce=nonce)
        return claims() if code == "good" else None

    monkeypatch.setattr(auth, "exchange_code", fake_exchange)

    async def go():
        cfg = auth.Config(client_id=CLIENT, client_secret="secret", db=":memory:", public_url="")
        app = make_app(auth_config=cfg, accounts=accounts)
        async with TestClient(TestServer(app)) as client:
            site = str(client.make_url("")).rstrip("/")
            origin = {"Origin": site}
            me = await (await client.get("/api/me")).json()
            assert me["accounts"] is True and me["user"] is None

            # Off to Google, with state and PKCE
            r = await client.get("/auth/google?next=/r/ABCD", allow_redirects=False)
            assert r.status == 302
            q = parse_qs(urlparse(r.headers["Location"]).query)
            assert q["client_id"] == [CLIENT] and q["code_challenge_method"] == ["S256"]
            assert q["code_challenge"][0] and q["nonce"][0] and q["scope"] == ["openid email profile"]
            assert q["redirect_uri"] == [site + "/auth/google/callback"]
            state = q["state"][0]

            # A wrong state, or a code Google won't swap, signs nobody in
            r = await client.get("/auth/google/callback?state=wrong&code=good", allow_redirects=False)
            assert r.headers["Location"] == "/?signin=expired"
            r = await client.get("/auth/google", allow_redirects=False)
            state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
            r = await client.get(f"/auth/google/callback?state={state}&code=bad", allow_redirects=False)
            assert r.headers["Location"] == "/?signin=failed"
            assert (await (await client.get("/api/me")).json())["user"] is None

            # Back from Google: signed in, and back to the room
            r = await client.get("/auth/google?next=/r/ABCD", allow_redirects=False)
            state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
            r = await client.get(f"/auth/google/callback?state={state}&code=good", allow_redirects=False)
            assert r.status == 302 and r.headers["Location"] == "/r/ABCD"
            assert seen["verifier"] and seen["nonce"] and seen["redirect_uri"] == site + "/auth/google/callback"
            cookie = r.cookies[auth.SESSION_COOKIE]
            assert cookie["httponly"] and cookie["samesite"] == "Lax"
            me = await (await client.get("/api/me")).json()
            assert me["user"]["email"] == "sam@example.com" and me["profile"]["stats"]["matches"] == 0

            # Changes need this site's Origin
            r = await client.post("/api/me/merge", json=guest_profile(2))
            assert r.status == 403
            r = await client.post("/api/me/merge", json=guest_profile(2), headers={"Origin": "https://evil.example"})
            assert r.status == 403
            res = await (await client.post("/api/me/merge", json=guest_profile(2), headers=origin)).json()
            assert res["added"] == 2 and res["profile"]["name"] == "Sammy"
            res = await (await client.put("/api/me/profile", json={"pattern": "star"}, headers=origin)).json()
            assert res["profile"]["pattern"] == "star"

            # Play a match while signed in: it lands in the account's history
            code = (await (await client.post("/api/rooms", json={"password": False})).json())["room"]
            # (Another site's page can't play as you: no Origin match, no account)
            other = await client.ws_connect(f"/ws/{code}", headers={"Origin": "https://evil.example"})
            await other.send_json({"type": "hello", "version": VERSION, "name": "X", "token": "tok-x"})
            await other.receive_json()
            room = app[ROOMS_KEY].get(code)
            assert room.members["tok-x"].account is None
            await other.send_json({"type": "leave"})  # (so the next one is host)
            await other.close()
            for _ in range(100):
                if "tok-x" not in room.members:
                    break
                await asyncio.sleep(0.01)
            ws = await client.ws_connect(f"/ws/{code}", headers=origin)
            await ws.send_json({"type": "hello", "version": VERSION, "name": "Sammy", "token": "tok-a"})
            assert (await ws.receive_json())["type"] == "welcome"
            assert (await ws.receive_json())["type"] == "lobby"
            assert room.members["tok-a"].account is not None
            await ws.send_json({"type": "settings", "map": "classic", "first_to": 1, "bots": ["bot:hard"]})
            await ws.send_json({"type": "start"})
            for _ in range(200_000):
                msg = await ws.receive_json(timeout=20)
                if msg["type"] == "results":
                    break
            await ws.close()
            p = (await (await client.get("/api/me")).json())["profile"]
            assert p["stats"]["matches"] == 3 and p["history"][0]["id"] == msg["match_id"]

            # Sign out: this browser's cookie stops working
            assert (await client.post("/auth/logout", headers=origin)).status == 200
            assert (await (await client.get("/api/me")).json())["user"] is None

            # Sign in again and delete the account
            r = await client.get("/auth/google", allow_redirects=False)
            state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
            await client.get(f"/auth/google/callback?state={state}&code=good", allow_redirects=False)
            assert (await client.delete("/api/me", headers=origin)).status == 200
            assert accounts.count() == 0
            assert (await (await client.get("/api/me")).json())["user"] is None
    run(go())


def test_a_kick_follows_a_signed_in_player_to_another_browser():
    from bonk_game.server.room import Room, RoomFull

    async def noop(msg):
        pass

    async def go():
        room = Room("ABCD")
        await room.join("host", "Ann", noop)
        await room.join("tok-1", "Bob", noop, account="u1")
        await room.kick("tok-1")
        with pytest.raises(RoomFull):
            await room.join("tok-2", "Bob", noop, account="u1")  # another browser, same account
        await room.join("tok-3", "Cat", noop)  # someone else is fine
    run(go())


def test_google_review_pages(monkeypatch):
    """What Google's brand review checks: a privacy policy with real content
    and a contact, linked from the home page, and a way to prove you own
    the site."""
    from bonk_game.server import web as web_mod
    page = web_mod.render_privacy("owner@example.com")
    assert "{{contact}}" not in page and 'href="mailto:owner@example.com"' in page
    for must in ("Google API Services User Data Policy", "Limited Use", "Delete my account", "openid"):
        assert must in page
    assert "{{contact}}" not in web_mod.render_privacy("")
    assert 'href="/privacy"' in web_mod.render_index() and 'href="/terms"' in web_mod.render_index()
    terms = web_mod.render_privacy("owner@example.com", name="terms.html")
    assert "{{contact}}" not in terms and "Terms of service" in terms and "Delete my account" in terms
    assert "google-site-verification" not in web_mod.render_index()
    monkeypatch.setattr(web_mod, "SITE_VERIFICATION", 'abc"123')
    assert '<meta name="google-site-verification" content="abc&quot;123">' in web_mod.render_index()


def test_account_perks_are_checked_by_the_server():
    """Any colour and the member patterns are for signed-in players."""
    from bonk_game.server.room import Room

    class Inbox:
        def __init__(self):
            self.msgs = []

        async def __call__(self, msg):
            self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    async def go():
        room = Room("ABCD")
        guest, member = Inbox(), Inbox()
        await room.join("g", "Guest", guest)
        await room.join("m", "Member", member, account="u1")
        assert member.msgs[0]["signed_in"] and not guest.msgs[0]["signed_in"]
        await room.handle("g", {"type": "own_color", "color": "#123456"})
        assert guest.msgs[-2]["message"] == "Sign in to pick any colour." and room.members["g"].own_color is None
        await room.handle("g", {"type": "pattern", "pattern": "galaxy"})
        assert room.members["g"].pattern == "plain"
        await room.handle("m", {"type": "own_color", "color": "#123456"})
        await room.handle("m", {"type": "pattern", "pattern": "galaxy"})
        await room.handle("m", {"type": "own_color", "color": "red; x"})  # (refused)
        seat = next(s for s in member.msgs[-1]["seats"] if s["id"] == room.members["m"].pid)
        assert seat["own_color"] == "#123456" and seat["pattern"] == "galaxy"
        await room.start()
        slot = next(s for s in room.match.describe()["slots"] if s["id"] == room.members["m"].pid)
        assert slot["color"] == "#123456" and slot["color_name"] == "Custom"
        await room.stop()
    run(go())
