"""Accounts (accounts.py) and signing in with Google (auth.py), issue #38.

Google's side is faked: auth.exchange_code is the only part that talks to
Google, and the tests replace it with claims like Google's.
"""
import asyncio
import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

from bonk_game.server import auth, profiles
from bonk_game.server.accounts import SESSION_DAYS, Accounts

aiohttp = pytest.importorskip("aiohttp")
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


def test_google_claims_are_checked():
    assert auth.check_claims(claims(), CLIENT) == ("g-1", "sam@example.com", "Sam")
    assert auth.check_claims(claims(aud="someone-else"), CLIENT) is None
    assert auth.check_claims(claims(iss="https://evil.example"), CLIENT) is None
    assert auth.check_claims(claims(exp=time.time() - 1), CLIENT) is None
    assert auth.check_claims(claims(sub=""), CLIENT) is None
    assert auth.check_claims(claims(email_verified=False), CLIENT)[1] == ""
    assert auth.check_claims(None, CLIENT) is None
    token = "x." + base64.urlsafe_b64encode(json.dumps(claims()).encode()).decode().rstrip("=") + ".sig"
    assert auth._decode_jwt_claims(token)["sub"] == "g-1"
    assert auth._decode_jwt_claims("garbage") is None


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
            assert (await r.json()) == {"accounts": False, "user": None}
            r = await client.get("/auth/google", allow_redirects=False)
            assert r.status == 404
            r = await client.get("/privacy")
            assert r.status == 200 and "Google" in await r.text()
    run(go())


def test_sign_in_play_and_delete(monkeypatch):
    """The whole flow: sign in, bring a browser profile along, play a match
    (the server records it), change your ball, sign out, delete."""
    from aiohttp.test_utils import TestClient, TestServer
    accounts = Accounts(":memory:")
    seen = {}

    async def fake_exchange(cfg, code, redirect_uri, verifier):
        seen.update(code=code, redirect_uri=redirect_uri, verifier=verifier)
        return claims() if code == "good" else None

    monkeypatch.setattr(auth, "exchange_code", fake_exchange)

    async def go():
        cfg = auth.Config(client_id=CLIENT, client_secret="secret", db=":memory:", public_url="")
        app = make_app(auth_config=cfg, accounts=accounts)
        async with TestClient(TestServer(app)) as client:
            site = str(client.make_url("")).rstrip("/")
            origin = {"Origin": site}
            assert (await (await client.get("/api/me")).json()) == {"accounts": True, "user": None}

            # Off to Google, with state and PKCE
            r = await client.get("/auth/google?next=/r/ABCD", allow_redirects=False)
            assert r.status == 302
            q = parse_qs(urlparse(r.headers["Location"]).query)
            assert q["client_id"] == [CLIENT] and q["code_challenge_method"] == ["S256"]
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
            assert seen["verifier"] and seen["redirect_uri"] == site + "/auth/google/callback"
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
            code = (await (await client.post("/api/rooms")).json())["room"]
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
