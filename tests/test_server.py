"""The web server (issue #23): matches, rooms and the WebSocket protocol."""
import asyncio
import json
import subprocess
import sys

import numpy as np
import pytest

from bonk_game.envs.utils.controls import Buttons
from bonk_game.envs.utils.maps import MAPS
from bonk_game.server import powerups as pu
from bonk_game.server import room as room_mod
from bonk_game.server.match import BEAT, Match
from bonk_game.server.room import LEAVE_GRACE, Room, RoomManager
from bonk_game.server.scene import level_shapes

aiohttp = pytest.importorskip("aiohttp")
from bonk_game.server.web import VERSION  # noqa: E402

SHAPE_TYPES = {"edges", "rect", "poly", "ball", "line", "pivot", "rail"}


def bots(n, level="medium"):
    return [{"kind": f"bot:{level}", "name": f"bot{i}"} for i in range(n)]


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(MAPS))
def test_every_map_draws_as_plain_shapes(name):
    from bonk_game.envs.utils.maps import make_map
    shapes = level_shapes(make_map(name))
    assert shapes and all(s["t"] in SHAPE_TYPES for s in shapes)
    json.dumps(shapes)


@pytest.mark.parametrize("name", list(MAPS))
def test_bot_match_runs_to_results(name):
    np.random.seed(0)
    m = Match(name, bots(4), first_to=2)
    seen = set()
    for _ in range(100_000):
        for ev in m.tick():
            seen.add(ev["e"])
        if m.finished:
            break
    assert m.finished
    assert {"beep", "go", "death", "score", "over"} <= seen
    res = m.results()
    assert max(res["scores"]) == 2
    json.dumps(m.snapshot())
    json.dumps(m.describe())


def test_countdown_then_play():
    m = Match("platform", bots(2), first_to=5)
    events = m.tick()
    assert m.phase == "countdown" and m.countdown_number() == 3
    assert events == [{"e": "beep"}]
    x = [p.x for p in m.env.players]
    for _ in range(int(3 * BEAT * 30) + 2):
        m.tick()
    assert m.phase == "play"
    for _ in range(5):
        m.tick()
    assert [p.x for p in m.env.players] != x  # bots are moving


def test_human_input_moves_their_ball():
    m = Match("classic", [{"kind": "human", "name": "a"}] + bots(1), first_to=5)
    m.set_phase("play")
    x = m.env.players[0].x
    for _ in range(5):
        m.set_input(0, [0, 0, 0, 1, 0])  # right
        m.tick()
    assert m.env.players[0].x > x
    assert m.inputs[0] == Buttons(right=True)


def test_stand_in_plays_for_a_missing_human_until_they_return():
    m = Match("classic", [{"kind": "human", "name": "a"}] + bots(1), first_to=5)
    m.stand_in(0)
    m.set_input(0, [0, 0, 0, 1, 0])
    assert m.snapshot()["stand_ins"] == [0]
    m.release(0)
    assert m.snapshot()["stand_ins"] == []
    assert m.inputs[0] == Buttons()


def test_server_does_not_need_pygame():
    code = ("import sys; import bonk_game.server.web, bonk_game.server.match; "
            "assert 'pygame' not in sys.modules, 'pygame was imported'")
    subprocess.run([sys.executable, "-c", code], check=True)


# ---------------------------------------------------------------------------
# Rooms (no network: members get a fake send())
# ---------------------------------------------------------------------------
class Inbox:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg):
        self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    def last(self, kind):
        return next(m for m in reversed(self.msgs) if m["type"] == kind)


def test_room_host_settings_and_permissions():
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        assert room.host == "a"
        assert a.last("welcome")["room"] == "ABCD"
        assert [m["name"] for m in b.last("lobby")["members"]] == ["Ann", "Bob"]

        await room.handle("b", {"type": "settings", "map": "swing"})
        assert b.last("error")["message"].startswith("Only the host")
        assert room.settings["map"] == "platform"

        await room.handle("a", {"type": "settings", "map": "swing", "first_to": 3,
                                "bots": ["bot:easy", "bot:hard"]})
        assert room.settings == {"map": "swing", "first_to": 3, "bots": ["bot:easy", "bot:hard"],
                                 "mode": "ffa", "round_time": None, "gravity": "normal", "speed": "normal",
                                 "power_ups": False, "power_kinds": pu.ALL_KINDS,
                                 "name": None, "password": None}
        await room.handle("a", {"type": "settings", "bots": ["nope"]})
        assert "Unknown bot" in a.last("error")["message"]
        await room.handle("a", {"type": "settings", "bots": ["bot:easy"] * 20})
        assert len(room.settings["bots"]) == 9
    run(go())


def test_room_needs_two_players_to_start():
    async def go():
        room = Room("ABCD")
        a = Inbox()
        await room.join("a", "Ann", a)
        await room.handle("a", {"type": "settings", "bots": []})
        await room.start()
        assert room.match is None
        assert "2 players" in a.last("error")["message"]
    run(go())


def test_disconnect_reconnect_and_host_handover(monkeypatch):
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.start()
        assert room.match is not None and room.match_tokens[:2] == ["a", "b"]
        assert a.last("match")["slots"][1]["name"] == "Bob"
        assert a.last("match")["slots"][2]["name"] == "Yellow bot"

        await room.disconnect("a")
        assert 0 in room.match.stand_ins
        assert room.host == "b"  # host moves to someone still here

        a2 = Inbox()
        await room.join("a", "", a2)  # same token: back in the same seat
        assert 0 not in room.match.stand_ins
        assert a2.last("match")["slots"][0]["id"] == room.members["a"].pid == a2.last("welcome")["you"]
        await room.stop()
    run(go())


def test_members_who_stay_away_leave_the_room():
    async def go():
        room = Room("ABCD")
        await room.join("a", "Ann", Inbox())
        await room.join("b", "Bob", Inbox())
        await room.disconnect("a")
        await room.prune(now=room.members["a"].left_at + LEAVE_GRACE - 1)
        assert "a" in room.members
        await room.prune(now=room.members["a"].left_at + LEAVE_GRACE + 1)
        assert list(room.members) == ["b"] and room.host == "b"
    run(go())


def test_leaving_on_purpose_gives_up_your_place_straight_away():
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.start()
        await room.handle("a", {"type": "leave"})
        assert list(room.members) == ["b"] and room.host == "b"
        assert 0 in room.match.stand_ins  # a bot finishes Ann's match
        assert [m["name"] for m in b.last("lobby")["members"]] == ["Bob"]
        await room.disconnect("a", a)  # (then the socket closes: nothing more happens)
        await room.handle("b", {"type": "leave"})
        assert room.members == {} and room.expired(now=room.empty_since + 10**6)
        await room.stop()
    run(go())


def test_room_codes_are_unique():
    rooms = RoomManager()
    codes = {rooms.create().code for _ in range(200)}
    assert len(codes) == 200
    assert all(len(c) == 4 and c.isalpha() and c.isupper() for c in codes)
    assert rooms.get(next(iter(codes)).lower()) is not None


# ---------------------------------------------------------------------------
# Over HTTP and WebSockets
# ---------------------------------------------------------------------------
def test_full_match_over_websockets(monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server.web import make_app

    monkeypatch.setattr(room_mod, "TICK_HZ", 3000)  # run the match fast

    async def go():
        client = TestClient(TestServer(make_app(RoomManager())))
        await client.start_server()
        try:
            assert (await (await client.get("/healthz")).text()) == "ok"
            page = await (await client.get("/r/ABCD")).text()
            assert "bonk" in page
            # Every script the page loads is served
            import re
            scripts = re.findall(r'<script src="([^"]+)"', page)
            assert len(scripts) > 5
            for src in scripts:
                assert (await client.get(src)).status == 200, src

            code = (await (await client.post("/api/rooms", json={"password": False})).json())["room"]
            info = await (await client.get(f"/api/rooms/{code}")).json()
            assert info == {"room": code, "players": 0, "locked": False}
            assert (await client.get("/api/rooms/ZZZZ")).status == 404

            ws = await client.ws_connect(f"/ws/{code}")
            await ws.send_json({"type": "hello", "version": VERSION, "name": "Ann", "token": "tok-a"})
            assert (await ws.receive_json())["type"] == "welcome"
            assert (await ws.receive_json())["type"] == "lobby"

            await ws.send_json({"type": "settings", "map": "classic", "first_to": 1,
                                "bots": ["bot:hard", "bot:hard", "bot:hard"]})
            await ws.send_json({"type": "start"})
            kinds = []
            for _ in range(200_000):
                msg = await ws.receive_json(timeout=10)
                kinds.append(msg["type"])
                if msg["type"] == "state" and len(kinds) == 10:
                    await ws.send_json({"type": "input", "b": [0, 1, 0, 0, 1]})
                if msg["type"] == "results":
                    break
            assert "match" in kinds and "state" in kinds
            # (at least: two knockouts in the same tick both count)
            assert msg["type"] == "results" and max(msg["scores"]) >= 1
            assert len(msg["slots"]) == 4
            await ws.close()

            bad = await client.ws_connect("/ws/ZZZZ")
            await bad.send_json({"type": "hello", "version": VERSION, "name": "Dan", "token": "d"})
            err = await bad.receive_json()
            assert err["type"] == "error" and err["fatal"]
        finally:
            await client.close()

    run(go())


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
def test_token_bucket():
    from bonk_game.server.limits import TokenBucket
    now = [0.0]
    b = TokenBucket(rate=2, burst=3, clock=lambda: now[0])
    assert [b.allow() for _ in range(4)] == [True, True, True, False]
    now[0] += 0.5  # one token back
    assert b.allow() and not b.allow()


def test_room_and_server_capacity(monkeypatch):
    from bonk_game.server import limits

    async def go():
        monkeypatch.setattr(limits, "MAX_MEMBERS", 2)
        room = Room("ABCD")
        await room.join("a", "Ann", Inbox())
        await room.join("b", "Bob", Inbox())
        with pytest.raises(room_mod.RoomFull):
            await room.join("c", "Cat", Inbox())
        await room.join("a", "Ann", Inbox())  # people already in can always come back

    run(go())
    monkeypatch.setattr(limits, "MAX_ROOMS", 3)
    rooms = RoomManager()
    for _ in range(3):
        rooms.create()
    with pytest.raises(room_mod.ServerFull):
        rooms.create()


def test_a_stale_disconnect_does_not_kick_a_reconnected_member():
    async def go():
        room = Room("ABCD")
        old, new = Inbox(), Inbox()
        await room.join("a", "Ann", old)
        await room.join("a", "Ann", new)  # refreshed before the old socket closed
        await room.disconnect("a", old)
        assert room.members["a"].connected
        await room.disconnect("a", new)
        assert not room.members["a"].connected
    run(go())


def _client(monkeypatch, **overrides):
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server import limits
    from bonk_game.server.web import make_app
    for k, v in overrides.items():
        monkeypatch.setattr(limits, k, v)
    return TestClient(TestServer(make_app(RoomManager())))


def test_room_creation_is_rate_limited(monkeypatch):
    async def go():
        client = _client(monkeypatch, ROOMS_PER_IP=3)
        await client.start_server()
        try:
            statuses = [(await client.post("/api/rooms", json={"password": False})).status for _ in range(5)]
            assert statuses == [200, 200, 200, 429, 429]
        finally:
            await client.close()
    run(go())


def test_connections_per_ip_are_capped(monkeypatch):
    async def go():
        client = _client(monkeypatch, CONNECTIONS_PER_IP=2)
        await client.start_server()
        try:
            code = (await (await client.post("/api/rooms", json={"password": False})).json())["room"]
            socks = []
            for i in range(2):
                ws = await client.ws_connect(f"/ws/{code}")
                await ws.send_json({"type": "hello", "version": VERSION, "name": f"p{i}", "token": f"t{i}"})
                assert (await ws.receive_json())["type"] == "welcome"
                socks.append(ws)
            extra = await client.ws_connect(f"/ws/{code}")
            err = await extra.receive_json()
            assert err["fatal"] and "Too many connections" in err["message"]
            await socks[0].close()
            await asyncio.sleep(0.05)
            again = await client.ws_connect(f"/ws/{code}")  # a slot freed up
            await again.send_json({"type": "hello", "version": VERSION, "name": "p9", "token": "t9"})
            assert (await again.receive_json())["type"] == "welcome"
        finally:
            await client.close()
    run(go())


def test_flooding_messages_gets_you_disconnected(monkeypatch):
    async def go():
        client = _client(monkeypatch, MESSAGES_PER_SECOND=1.0, MESSAGE_BURST=5.0, MAX_DROPPED=20)
        await client.start_server()
        try:
            code = (await (await client.post("/api/rooms", json={"password": False})).json())["room"]
            ws = await client.ws_connect(f"/ws/{code}")
            await ws.send_json({"type": "hello", "version": VERSION, "name": "Ann", "token": "t"})
            for _ in range(100):
                await ws.send_json({"type": "input", "b": [0, 0, 0, 0, 0]})
            msgs = []
            while True:
                m = await ws.receive(timeout=5)
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                msgs.append(json.loads(m.data))
            assert any(m["type"] == "error" and "too much" in m["message"] for m in msgs)
        finally:
            await client.close()
    run(go())


# ---------------------------------------------------------------------------
# Party features: colours, kick, rematch votes, emotes
# ---------------------------------------------------------------------------
def test_people_pick_colours_and_bots_take_the_rest():
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.handle("a", {"type": "settings", "bots": ["bot:easy", "bot:easy"]})
        await room.handle("b", {"type": "color", "color": 0})   # Bob wants red
        await room.handle("a", {"type": "color", "color": 0})   # taken
        assert "Someone else" in a.last("error")["message"]
        await room.handle("a", {"type": "color", "color": 7})
        await room.handle("a", {"type": "color", "color": 99})
        assert "Unknown colour" in a.last("error")["message"]
        seats = a.last("lobby")["seats"]
        assert [s["color"] for s in seats] == [7, 0, 1, 2]
        await room.start()
        slots = a.last("match")["slots"]
        assert [s["color_name"] for s in slots] == ["Cyan", "Red", "Blue", "Yellow"]
        assert slots[2]["name"] == "Blue bot"
        assert room.match.env.players[0].color == (59, 201, 219)
        await room.stop()
    run(go())


def test_host_can_remove_someone_for_good():
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        pa, pb = room.members["a"].pid, room.members["b"].pid
        await room.handle("b", {"type": "kick", "id": pa})   # not the host
        assert "a" in room.members
        await room.handle("a", {"type": "kick", "id": pa})   # can't remove yourself
        assert "a" in room.members
        await room.handle("a", {"type": "kick", "id": "b"})  # (a token, not an id: nothing)
        assert "b" in room.members
        await room.handle("a", {"type": "kick", "id": pb})
        assert "b" not in room.members
        assert b.last("error")["fatal"]
        with pytest.raises(room_mod.RoomFull, match="removed"):
            await room.join("b", "Bob", Inbox())
        # A connection left open after being removed changes nothing
        for msg in ({"type": "name", "name": "Bobby"}, {"type": "chat", "text": "hi"},
                    {"type": "report_player", "id": pa}, {"type": "color", "color": 3}):
            await room.handle("b", msg)
        assert "b" not in room.members and not [m for m in a.msgs if m.get("text") == "hi"]
    run(go())


def test_kicking_a_player_mid_match_hands_their_ball_to_a_bot():
    async def go():
        room = Room("ABCD")
        await room.join("a", "Ann", Inbox())
        await room.join("b", "Bob", Inbox())
        await room.start()
        await room.handle("a", {"type": "kick", "id": room.members["b"].pid})
        assert 1 in room.match.stand_ins
        await room.stop()
    run(go())


def test_rematch_starts_when_everyone_votes(monkeypatch):
    monkeypatch.setattr(room_mod, "TICK_HZ", 3000)

    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.handle("a", {"type": "settings", "map": "classic", "first_to": 1,
                                "bots": ["bot:hard"] * 3})
        await room.start()
        await room.task
        assert room.results is not None and room.match is None
        await room.handle("b", {"type": "vote"})
        assert a.last("lobby")["votes"] == [room.members["b"].pid] and room.match is None
        await room.handle("b", {"type": "vote"})   # changed their mind
        assert room.votes == set()
        await room.handle("b", {"type": "vote"})
        await room.handle("a", {"type": "vote"})
        assert room.match is not None and room.votes == set()
        await room.stop()
    run(go())


def test_votes_from_people_who_left_dont_block_a_rematch(monkeypatch):
    monkeypatch.setattr(room_mod, "TICK_HZ", 3000)

    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.handle("a", {"type": "settings", "map": "classic", "first_to": 1})
        await room.start()
        await room.task
        await room.handle("a", {"type": "vote"})
        await room.disconnect("b", b)   # Bob leaves: Ann is the only one here, and voted
        assert room.match is not None
        await room.stop()
    run(go())


def test_emotes_reach_everyone_but_not_too_often():
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.handle("a", {"type": "emote", "id": 0})   # no match yet: ignored
        await room.start()
        await room.handle("b", {"type": "emote", "id": 2})
        await room.handle("b", {"type": "emote", "id": 1})   # too soon
        await room.handle("b", {"type": "emote", "id": 9})   # not an emote
        emotes = [m for m in a.msgs if m["type"] == "emote"]
        assert emotes == [{"type": "emote", "slot": 1, "id": 2}]
        await room.stop()
    run(go())


def test_going_to_the_lobby_mid_match_hands_your_ball_to_a_bot_until_you_come_back():
    async def go():
        room = Room("ABCD")
        await room.join("a", "Ann", Inbox())
        await room.join("b", "Bob", Inbox())
        await room.handle("b", {"type": "away"})   # no match yet: nothing
        await room.start()
        await room.handle("b", {"type": "away"})
        assert 1 in room.match.stand_ins and "b" in room.members
        await room.handle("b", {"type": "back"})
        assert 1 not in room.match.stand_ins
        await room.handle("b", {"type": "away"})
        await room.handle("b", {"type": "leave"})   # ← Leave from the lobby: gone, the bot plays on
        assert "b" not in room.members and 1 in room.match.stand_ins
        await room.stop()
    run(go())


def test_the_host_can_end_a_match_early():
    async def go():
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a)
        await room.join("b", "Bob", b)
        await room.handle("a", {"type": "settings", "bots": ["bot:medium"] * 3})
        await room.start()
        await room.handle("b", {"type": "end_match"})   # not the host
        assert room.match is not None and "Only the host" in b.last("error")["message"]
        await room.handle("a", {"type": "end_match"})
        await room.task
        # Back to the lobby: no results, nothing counted, and the room says why
        assert room.match is None and room.results is None and room.ending is None
        assert a.last("lobby")["phase"] == "lobby"
        assert not any(m["type"] == "results" for m in a.msgs + b.msgs)
        assert b.last("chat")["text"] == "Ann ended the match"
        # The map can change now, and the next match starts as usual
        await room.handle("a", {"type": "settings", "map": "classic"})
        assert room.settings["map"] == "classic"
        await room.start()
        assert room.match is not None
        await room.stop()
    run(go())
