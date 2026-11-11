"""A busy server (room.py: RoomManager.busy) lets nobody new in, and says so
(web.py: busy_response; the page waits and tries again: js/core.js busy).
People already in a room stay, and can come back."""
import asyncio

import pytest

from bonk_game.server import limits, metrics
from bonk_game.server.room import RoomManager, ServerBusy, ServerFull


class Inbox:
    async def __call__(self, msg):
        pass


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh_stats(monkeypatch):
    stats = metrics.Stats(clock=lambda: 1000.0)
    monkeypatch.setattr(metrics, "STATS", stats)
    return stats


def test_too_many_people_turns_new_ones_away_but_not_the_ones_here(monkeypatch, fresh_stats):
    monkeypatch.setattr(limits, "MAX_PEOPLE", 2)

    async def go():
        rooms = RoomManager()
        room = rooms.create()
        await room.join("a", "Ann", Inbox())
        assert rooms.busy() is None
        await room.join("b", "Bob", Inbox())
        assert rooms.busy() == "full"
        with pytest.raises(ServerBusy):
            await room.join("c", "Cat", Inbox())  # someone new
        with pytest.raises(ServerFull):
            rooms.create()
        with pytest.raises(ServerFull):
            rooms.quick_play()
        await room.disconnect("b")
        await room.join("b", "Bob", Inbox())  # back after a refresh: fine
        back = rooms.create("WXYZ")  # a room coming back after a restart: fine
        assert back.code == "WXYZ"
        assert fresh_stats.refused_busy == 3
        snap = fresh_stats.snapshot(rooms)
        assert snap["busy"] is True and snap["max_people"] == 2 and snap["refused_busy_total"] == 3
        await room.disconnect("a")
        await room.disconnect("b")
        assert rooms.busy() is None  # (they've gone: room again)
        for r in list(rooms.rooms.values()):
            await r.stop()
    run(go())


def test_matches_falling_behind_make_it_busy_for_a_while(fresh_stats):
    rooms = RoomManager()
    fresh_stats.late_at.extend([990.0, 995.0])
    assert rooms.busy() is None  # (two: a hiccup)
    fresh_stats.late_at.append(999.0)
    assert rooms.busy() == "behind"
    fresh_stats.late_at.clear()
    fresh_stats.late_at.extend([900.0, 950.0, 960.0])  # (long ago)
    assert rooms.busy() is None


def test_busy_over_http_and_websockets(monkeypatch):
    pytest.importorskip("aiohttp")
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server.web import ROOMS, VERSION, make_app

    async def go():
        app = make_app()
        async with TestClient(TestServer(app)) as client:
            code = (await (await client.post("/api/rooms", json={"password": False})).json())["room"]
            ws = await client.ws_connect(f"/ws/{code}")
            await ws.send_json({"type": "hello", "name": "Ann", "token": "t-a", "version": VERSION})
            assert (await ws.receive_json())["type"] == "welcome"
            monkeypatch.setattr(limits, "MAX_PEOPLE", 1)  # (Ann fills it)
            assert app[ROOMS].busy() == "full"
            for path in ("/api/quickplay", "/api/rooms"):
                r = await client.post(path)
                body = await r.json()
                assert r.status == 503 and body["busy"] is True and body["retry"] == limits.BUSY_RETRY
                assert r.headers["Retry-After"] == str(limits.BUSY_RETRY)
            other = await client.ws_connect(f"/ws/{code}")
            await other.send_json({"type": "hello", "name": "Bob", "token": "t-b", "version": VERSION})
            msg = await other.receive_json()
            assert msg["type"] == "error" and msg["busy"] is True and msg["fatal"] is True
            await other.close()
            await ws.close()
    run(go())
