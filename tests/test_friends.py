"""Friends (accounts.py: befriend, unfriend, friends; room.py: "befriend";
web.py: /api/friends)."""
import asyncio
import json

import pytest

aiohttp = pytest.importorskip("aiohttp")  # (the web server's packages; the training CI job has none)

from bonk_game.server import accounts as accounts_mod  # noqa: E402
from bonk_game.server import auth  # noqa: E402
from bonk_game.server.accounts import Accounts  # noqa: E402
from bonk_game.server.room import RoomManager  # noqa: E402

CLIENT = "client-123.apps.googleusercontent.com"


def run(coro):
    return asyncio.run(coro)


class Inbox:
    def __init__(self):
        self.got = []

    async def __call__(self, msg):
        self.got.append(json.loads(msg) if isinstance(msg, (str, bytes)) else msg)

    def notices(self):
        return [m for m in self.got if m.get("type") in ("notice", "error")]


def people(n=3):
    acc = Accounts(":memory:")
    ids = [acc.sign_in(f"g-{k}", name=name)[0]["id"] for k, name in enumerate(["Ann", "Bob", "Cat"][:n])]
    return acc, ids


def test_a_request_back_makes_friends_and_either_can_end_it():
    acc, (ann, bob, cat) = people()
    assert acc.befriend(ann, bob) == "sent"
    assert acc.befriend(ann, bob) == "already"  # (asked already)
    assert [r["name"] for r in acc.friends(bob)["incoming"]] == ["Ann"]
    assert [r["name"] for r in acc.friends(ann)["outgoing"]] == ["Bob"]
    assert acc.befriend(bob, ann) == "friends"
    assert acc.are_friends(ann, bob) and acc.befriend(ann, bob) == "already"
    assert acc.friends(ann) == {"friends": [{"id": bob, "name": "Bob", "ball": acc.friends(ann)["friends"][0]["ball"]}],
                                "incoming": [], "outgoing": []}
    assert acc.befriend(ann, ann) == "no" and acc.befriend(ann, "u-nobody") == "no"
    acc.unfriend(bob, ann)
    assert not acc.are_friends(ann, bob) and acc.friends(ann)["friends"] == []
    # Turning down a request (or taking yours back) clears it
    acc.befriend(cat, ann)
    acc.unfriend(ann, cat)
    assert acc.friends(ann)["incoming"] == [] and acc.friends(cat)["outgoing"] == []


def test_friends_and_requests_have_limits_and_go_with_the_account(monkeypatch):
    acc, (ann, bob, cat) = people()
    monkeypatch.setattr(accounts_mod, "MAX_REQUESTS", 1)
    assert acc.befriend(ann, bob) == "sent"
    assert acc.befriend(ann, cat) == "full"  # (one waiting already)
    monkeypatch.setattr(accounts_mod, "MAX_FRIENDS", 1)
    assert acc.befriend(bob, ann) == "friends"
    assert acc.befriend(cat, ann) == "sent" and acc.befriend(ann, cat) == "full"  # (Ann has her 1 friend)
    acc.delete(bob)
    assert acc.friends(ann)["friends"] == []


def test_asking_someone_in_a_room_tells_them_wherever_they_are():
    async def go():
        acc, (ann, bob, cat) = people()
        rooms = RoomManager()
        rooms.ratings = acc
        here, there = rooms.create(), rooms.create()
        a, b, b_away, guest = Inbox(), Inbox(), Inbox(), Inbox()
        await here.join("ta", "Ann", a, account=ann)
        await here.join("tb", "Bob", b, account=bob)
        await there.join("tb2", "Bob", b_away, account=bob)  # (Bob on another device, in another room)
        await here.join("tg", "Gus", guest)
        bob_pid = here.members["tb"].pid
        members = {m["id"]: m for m in here.lobby()["members"]}
        assert members[bob_pid].get("signed_in") and not members[here.members["tg"].pid].get("signed_in")
        await here.handle("ta", {"type": "befriend", "id": bob_pid})
        assert a.notices()[-1]["message"] == "Friend request sent to Bob."
        assert any(n.get("friends") == "request" and "Ann wants to be friends" in n["message"] for n in b_away.notices())
        await here.handle("tb", {"type": "befriend", "id": here.members["ta"].pid})
        assert acc.are_friends(ann, bob)
        assert any(n.get("friends") == "friends" for n in a.notices())
        # Guests can't
        await here.handle("ta", {"type": "befriend", "id": here.members["tg"].pid})
        assert "isn't signed in" in a.notices()[-1]["message"]
        await here.handle("tg", {"type": "befriend", "id": bob_pid})
        assert guest.notices()[-1]["message"] == "Sign in to add friends."
        # Where they are: rooms say so (not a private room's password)
        there.settings["password"] = "secret"
        where = rooms.where({bob, cat})
        assert set(where) == {bob} and where[bob]["room"] in (here.code, there.code)
        assert "password" not in str(where) and "secret" not in str(where)
        for r in (here, there):
            await r.stop()
    run(go())


def test_the_friends_api(monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server.web import make_app
    acc, (ann, bob, cat) = people()

    async def go():
        cfg = auth.Config(client_id=CLIENT, client_secret="secret", db=":memory:", public_url="")
        app = make_app(auth_config=cfg, accounts=acc)
        async with TestClient(TestServer(app)) as client:
            site = str(client.make_url("")).rstrip("/")
            as_ann = {"Cookie": f"{auth.SESSION_COOKIE}={acc.new_session(ann)}", "Origin": site}
            as_bob = {"Cookie": f"{auth.SESSION_COOKIE}={acc.new_session(bob)}", "Origin": site}
            assert (await client.get("/api/friends")).status == 401
            acc.befriend(bob, ann)
            d = await (await client.get("/api/friends", headers=as_ann)).json()
            assert [r["name"] for r in d["incoming"]] == ["Bob"]
            # Only a waiting request can be accepted by id; not someone who didn't ask
            assert (await client.post(f"/api/friends/{cat}", headers=as_ann)).status == 404
            assert (await client.post(f"/api/friends/{bob}", headers={"Cookie": as_ann["Cookie"]})).status == 403
            r = await (await client.post(f"/api/friends/{bob}", headers=as_ann)).json()
            assert r["result"] == "friends"
            d = await (await client.get("/api/friends", headers=as_bob)).json()
            assert d["friends"][0]["name"] == "Ann" and d["friends"][0]["online"] is False and d["friends"][0]["where"] is None
            assert (await client.delete(f"/api/friends/{ann}", headers=as_bob)).status == 200
            assert (await (await client.get("/api/friends", headers=as_ann)).json())["friends"] == []
    run(go())
