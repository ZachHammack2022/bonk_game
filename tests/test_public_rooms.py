"""The game browser (every room, by name; some with a password), quick
play and joining a match that's on (#35)."""
import asyncio
import json

import pytest

from bonk_game.server import lobby
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


def test_every_room_is_listed_by_its_name_and_never_with_its_password():
    async def go():
        rooms = RoomManager()
        room = rooms.create()
        assert rooms.listed() == []  # (nobody there yet)
        await room.join("a", "Ann", Inbox())
        [listed] = rooms.listed()
        assert listed["name"] == "Ann's room" and listed["locked"] is False
        await room.handle("a", {"type": "settings", "name": "  Friday   night ", "password": True})
        assert room.settings["name"] == "Friday night"
        pw = room.settings["password"]
        assert len(pw) == 6 and set(pw) <= set(lobby.PASSWORD_ALPHABET)
        [listed] = rooms.listed()
        assert pw not in json.dumps(rooms.browse())
        assert listed == {"room": room.code, "name": "Friday night", "locked": True,
                          "map": "Sinking Swing", "map_id": "swing",
                          "mode": "Free-for-all", "mode_id": "ffa", "goal": "First to 5", "people": 1,
                          "bots": 1, "most": 6, "names": ["Ann"], "playing": False, "elapsed": None,
                          "open": True, "power_ups": False, "gravity": "normal", "speed": "normal", "quick": False,
                          "host": "Ann", "ping": None}
        room.members["a"].note_network(0, {"rtt": 84.4})
        assert rooms.listed()[0]["ping"] == 84
        await room.disconnect("a")
        assert rooms.listed() == []  # (nobody there)
    run(go())


def test_the_host_names_the_room_and_sets_its_password():
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.handle("b", {"type": "settings", "name": "Mine now"})
        assert room.settings["name"] is None  # (only the host)
        await room.handle("a", {"type": "settings", "name": "x" * 50})
        assert room.settings["name"] == "x" * lobby.ROOM_NAME_LEN
        await room.handle("a", {"type": "settings", "name": "fuck this"})
        assert room.settings["name"] is None and b.all("lobby")[-1]["title"] == "Ann's room"
        await room.handle("a", {"type": "settings", "name": 5})
        assert "name" in a.all("error")[-1]["message"]
        await room.handle("a", {"type": "settings", "password": True})
        pw = room.settings["password"]
        assert pw and b.all("lobby")[-1]["settings"]["password"] == pw  # (people in the room can invite)
        # Nobody types a password in: the server makes them up
        await room.handle("a", {"type": "settings", "password": "hunter2"})
        assert "private" in a.all("error")[-1]["message"] and room.settings["password"] == pw
        await room.handle("a", {"type": "settings", "password": None})
        assert room.settings["password"] is None
    run(go())


def test_a_room_with_a_password_needs_it_to_join_but_not_to_come_back():
    async def go():
        room = Room("ABCD")
        room.settings["password"] = "k7mq2x"
        await room.join("a", "Ann", Inbox(), password="k7mq2x")
        with pytest.raises(room_mod.PasswordNeeded) as e:
            await room.join("b", "Bob", Inbox())
        assert not e.value.wrong
        with pytest.raises(room_mod.PasswordNeeded) as e:
            await room.join("b", "Bob", Inbox(), password="nope")
        assert e.value.wrong and "b" not in room.members
        await room.join("b", "Bob", Inbox(), password=" k7mq2x")
        await room.disconnect("b")
        await room.join("b", "Bob", Inbox())  # (a refresh: already in the room)
        assert set(room.members) == {"a", "b"}
    run(go())


def test_quick_play_fills_the_busiest_public_room_or_makes_one_with_bots():
    async def go():
        rooms = RoomManager()
        made, new = rooms.quick_play()
        assert new and made.quick and made.settings["password"] is None and made.settings["mode"] == "knockouts"
        assert len(made.settings["bots"]) == 3
        again, new = rooms.quick_play()
        assert again is made and not new  # (nobody's there yet, but it's waiting for people)
        locked = rooms.create()
        locked.settings["password"] = "secret"
        for t in "wxyz":
            await locked.join(t, t, Inbox(), password="secret")  # (busier, but has a password)
        busy = rooms.create()
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


def test_quick_play_bots_step_aside_as_people_come():
    async def go():
        room, _ = RoomManager().quick_play()
        for k, t in enumerate("abcde"):
            await room.join(t, t, Inbox())
            humans, bots = room.seats()
            assert len(humans) == k + 1 and len(bots) == max(0, lobby.QUICK_FILL - (k + 1))
        assert [s["kind"] for s in room.lineup()] == ["human"] * 5
        room.quick = False  # (an ordinary room keeps every bot the host added)
        assert len(room.seats()[1]) == 1
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
            assert (await (await client.get("/api/public")).json()) == {"rooms": [], "online": 0,
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


def test_the_browser_lists_rooms_with_people_the_fullest_first():
    async def go():
        rooms = RoomManager()
        one, two, empty = rooms.create(), rooms.create(), rooms.create()
        await one.join("a", "Ann", Inbox())
        two.settings["password"] = "pw"
        await two.join("b", "Bo", Inbox(), password="pw")
        await two.join("c", "Cy", Inbox(), password="pw")
        listed = rooms.browse()
        assert [(r["room"], r["locked"]) for r in listed["rooms"]] == [(two.code, True), (one.code, False)]
        assert listed["online"] == 3 and listed["more"] == 0
        assert empty.code not in json.dumps(listed) and '"pw"' not in json.dumps(listed)
    run(go())


def test_a_listed_match_shows_how_long_it_has_been_on():
    async def go():
        rooms = RoomManager()
        room = rooms.create()
        await room.join("a", "Ann", Inbox())
        await room.handle("a", {"type": "settings", "mode": "lives"})
        await room.start()
        room.match.tick_count = 30 * 75
        [listed] = rooms.listed()
        assert listed["playing"] and listed["elapsed"] == 75 and listed["goal"] == "3 lives"
        await room.stop()
    run(go())


def test_new_rooms_get_a_name_and_a_password_unless_asked_not_to():
    pytest.importorskip("aiohttp")
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server.web import make_app

    async def go():
        app = make_app()
        async with TestClient(TestServer(app)) as client:
            plain = await (await client.post("/api/rooms")).json()
            assert plain["name"] is None and len(plain["password"]) == 6
            named = await (await client.post("/api/rooms", json={"name": "Sam's room", "password": False})).json()
            assert named["name"] == "Sam's room" and named["password"] is None
            junk = await (await client.post("/api/rooms", data="not json")).json()
            assert junk["password"]
            info = await (await client.get(f"/api/rooms/{plain['room']}")).json()
            assert info["locked"] is True
            assert (await client.get("/play")).status == 200
    run(go())


def test_joining_over_the_websocket_asks_for_the_password():
    pytest.importorskip("aiohttp")
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server import web as web_mod

    async def go():
        app = web_mod.make_app()
        async with TestClient(TestServer(app)) as client:
            made = await (await client.post("/api/rooms", json={"name": "Den"})).json()
            code, pw = made["room"], made["password"]

            async def hello(token, password=None):
                ws = await client.ws_connect(f"/ws/{code}")
                msg = {"type": "hello", "name": token, "token": token, "version": web_mod.VERSION}
                if password is not None:
                    msg["password"] = password
                await ws.send_json(msg)
                reply = await ws.receive_json()
                return ws, reply

            ws, reply = await hello("tok-a")
            assert reply["type"] == "error" and reply["password"] and not reply["wrong"]
            await ws.close()
            ws, reply = await hello("tok-a", "wrong")
            assert reply["password"] and reply["wrong"]
            await ws.close()
            ws, reply = await hello("tok-a", pw)
            assert reply["type"] == "welcome"
            lobby_msg = await ws.receive_json()
            assert lobby_msg["title"] == "Den" and lobby_msg["settings"]["password"] == pw
            await ws.close()
            # Guessing: a few wrong passwords, then a minute's wait
            for _ in range(web_mod.WRONG_PASSWORDS - 1):
                ws, reply = await hello("tok-b", "guess")
                await ws.close()
            ws, reply = await hello("tok-b", pw)  # (right: always fine)
            assert reply["type"] == "welcome"
            await ws.close()
            ws, reply = await hello("tok-c", "guess")
            ws2, reply2 = await hello("tok-c", "guess2")
            assert "Too many wrong passwords" in reply2["message"]
            await ws.close()
            await ws2.close()
    run(go())
