"""Public rooms, quick play and joining a match that's on (#35)."""
import asyncio
import json

import pytest

from bonk_game.server import room as room_mod
from bonk_game.server.room import Room, RoomManager


class Inbox:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg):
        self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    def all(self, kind):
        return [m for m in self.msgs if m["type"] == kind]


def run(coro):
    return asyncio.run(coro)


def test_rooms_are_private_until_the_host_lists_them():
    async def go():
        rooms = RoomManager()
        room = rooms.create()
        await room.join("a", "Ann", Inbox())
        assert rooms.public() == []
        await room.handle("a", {"type": "settings", "public": "yes"})
        assert room.settings["public"] is False
        await room.handle("a", {"type": "settings", "public": True})
        [listed] = rooms.public()
        assert listed == {"room": room.code, "map": "Floating Platform", "map_id": "platform",
                          "mode": "Free-for-all", "mode_id": "ffa", "goal": "First to 5", "people": 1,
                          "bots": 1, "most": 6, "names": ["Ann"], "playing": False, "elapsed": None,
                          "open": True, "power_ups": False, "gravity": "normal", "speed": "normal", "quick": False,
                          "host": "Ann"}
        await room.disconnect("a")
        assert rooms.public() == []  # (nobody there)
    run(go())


def test_quick_play_fills_the_busiest_public_room_or_makes_one_with_bots():
    async def go():
        rooms = RoomManager()
        made, new = rooms.quick_play()
        assert new and made.quick and made.settings["public"] and made.settings["mode"] == "knockouts"
        assert len(made.settings["bots"]) == 3
        again, new = rooms.quick_play()
        assert again is made and not new  # (nobody's there yet, but it's waiting for people)
        busy = rooms.create()
        busy.settings["public"] = True
        for t in "abc":
            await busy.join(t, t, Inbox())
        assert rooms.quick_play() == (busy, False)
        busy.settings["map"] = "classic"
        for t in "defgh":
            await busy.join(t, t, Inbox())  # 8 people: Classic is full
        assert rooms.quick_play() == (made, False)
        assert rooms.quick_play(allow_new=lambda: False)[0] is made
        made.closing = True
        assert rooms.quick_play(allow_new=lambda: False) == (None, False)
        for r in list(rooms.rooms.values()):
            await r.stop()
    run(go())


def test_quick_play_rooms_start_by_themselves(monkeypatch):
    monkeypatch.setattr(room_mod, "AUTO_START", 0.01)

    async def go():
        room, _ = RoomManager().quick_play()
        await room.join("a", "Ann", Inbox())
        await asyncio.sleep(0.1)
        assert room.match is not None and room.match_tokens[0] == "a"
        assert len(room.match.slots) == 4
        await room.stop()
    run(go())


def test_someone_joining_a_respawn_match_takes_over_a_bot_straight_away():
    async def go():
        room = Room("ABCD")
        a, w = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.handle("a", {"type": "settings", "mode": "knockouts", "bots": ["bot:easy", "bot:hard"]})
        await room.start()
        await asyncio.sleep(0.2)
        await room.join("w", "Wes", w)
        assert room.match_tokens == ["a", None, "w"]  # (the last bot)
        assert room.match.controllers[2] is None and room.match.slots[2]["kind"] == "human"
        [seat] = a.all("seat")
        assert seat["slot"] == 2 and seat["info"]["name"] == "Wes" and seat["info"]["id"] == room.members["w"].pid
        assert seat["info"]["color_name"] == "Yellow"  # (the bot's colour)
        assert "took over from Yellow bot" in w.all("notice")[-1]["message"]
        await room.handle("w", {"type": "input", "b": [0, 1, 0, 0, 0]})
        assert room.match.inputs[2][1]
        assert w.all("lobby")[-1]["playing"] == [room.members["a"].pid, None, room.members["w"].pid]
        await room.stop()
    run(go())


def test_in_round_modes_they_wait_for_the_next_round(monkeypatch):
    async def go():
        room = Room("ABCD")
        await room.join("a", "Ann", Inbox())
        await room.handle("a", {"type": "settings", "map": "classic", "bots": ["bot:hard"]})
        await room.start()
        room.match.set_phase("play")
        w = Inbox()
        await room.join("w", "Wes", w)
        assert room.waiting == ["w"] and room.match_tokens == ["a", None]
        assert "at the next round" in w.all("notice")[-1]["message"]
        room.match.set_phase("scored")
        await room.drop_in()
        assert room.match_tokens == ["a", "w"] and room.waiting == []
        await room.stop()
    run(go())


def test_with_no_bot_to_take_over_they_watch(monkeypatch):
    async def go():
        room = Room("ABCD")
        await room.join("a", "Ann", Inbox())
        await room.join("b", "Bob", Inbox())
        await room.handle("a", {"type": "settings", "mode": "knockouts", "bots": []})
        await room.start()
        w = Inbox()
        await room.join("w", "Wes", w)
        assert room.match_tokens == ["a", "b"] and room.waiting == []
        assert "next one" in w.all("notice")[-1]["message"]
        await room.stop()
    run(go())


def test_people_who_drop_in_get_the_match_in_their_history(monkeypatch):
    monkeypatch.setattr(room_mod, "TICK_HZ", 3000)
    recorded = []

    async def go():
        room = Room("ABCD", recorder=lambda account, entry: recorded.append(account))
        await room.join("a", "Ann", Inbox())
        await room.handle("a", {"type": "settings", "mode": "lives", "first_to": 1, "bots": ["bot:hard"]})
        await room.start()
        await room.join("w", "Wes", Inbox(), account="acc-w")
        await room.task
        assert recorded == ["acc-w"]
    run(go())


def test_the_public_list_and_quick_play_over_http():
    pytest.importorskip("aiohttp")  # (the training job runs without the server's packages)
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server.web import VERSION, make_app

    async def go():
        app = make_app()
        async with TestClient(TestServer(app)) as client:
            assert (await (await client.get("/api/public")).json()) == {"rooms": [], "online": 0, "private": 0,
                                                                        "more": 0}
            r = await client.post("/api/quickplay")
            body = await r.json()
            assert r.status == 200 and body["new"] and len(body["room"]) == 4
            ws = await client.ws_connect(f"/ws/{body['room']}")
            await ws.send_json({"type": "hello", "name": "Sam", "token": "t", "version": VERSION})
            welcome = await ws.receive_json()
            assert welcome["type"] == "welcome" and welcome["you"] != "t"
            rooms = (await (await client.get("/api/public")).json())["rooms"]
            assert [x["room"] for x in rooms] == [body["room"]] and rooms[0]["people"] == 1
            await ws.close()
    run(go())


@pytest.mark.parametrize("bad", [None, 3, "x"])
def test_unknown_ids_do_nothing(bad):
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.handle("a", {"type": "kick", "id": bad})
        await room.handle("a", {"type": "report_player", "id": bad})
        assert set(room.members) == {"a", "b"}
    run(go())


def test_the_browser_counts_private_rooms_but_never_lists_them():
    async def go():
        rooms = RoomManager()
        public, private, empty = rooms.create(), rooms.create(), rooms.create()
        await public.join("a", "Ann", Inbox())
        await public.handle("a", {"type": "settings", "public": True})
        await private.join("b", "Bo", Inbox())
        await private.join("c", "Cy", Inbox())
        listed = rooms.browse()
        assert [r["room"] for r in listed["rooms"]] == [public.code]
        assert listed["online"] == 3 and listed["private"] == 1 and listed["more"] == 0
        assert private.code not in json.dumps(listed) and empty.code not in json.dumps(listed)
    run(go())


def test_a_listed_match_shows_how_long_it_has_been_on():
    async def go():
        rooms = RoomManager()
        room = rooms.create()
        await room.join("a", "Ann", Inbox())
        await room.handle("a", {"type": "settings", "public": True, "mode": "lives"})
        await room.start()
        room.match.tick_count = 30 * 75
        [listed] = rooms.public()
        assert listed["playing"] and listed["elapsed"] == 75 and listed["goal"] == "3 lives"
        await room.stop()
    run(go())


def test_new_rooms_can_be_public_from_the_start():
    pytest.importorskip("aiohttp")
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server.web import make_app

    async def go():
        app = make_app()
        async with TestClient(TestServer(app)) as client:
            plain = await (await client.post("/api/rooms")).json()
            assert plain["public"] is False
            listed = await (await client.post("/api/rooms", json={"public": True})).json()
            assert listed["public"] is True
            junk = await (await client.post("/api/rooms", data="not json")).json()
            assert junk["public"] is False
            assert (await client.get("/play")).status == 200
    run(go())
