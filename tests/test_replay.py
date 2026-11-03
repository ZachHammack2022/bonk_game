"""Replays and the killcam (issue #40): a match's seed and inputs, played
back through the same physics, give exactly the same match."""
import asyncio
import json
import random

import numpy as np
import pytest

from bonk_game.envs.utils.controls import Buttons
from bonk_game.server import replay
from bonk_game.server.match import Match, input_code, input_from_code


def play_match(map_name, mode="ffa", power_ups=False, goal=3, n=4, ticks=30 * 90, noise=True):
    """A bot match; other code drawing random numbers in between (other
    rooms, agents) must not change it."""
    m = Match(map_name, [{"kind": "bot:hard", "name": f"b{i}"} for i in range(n)], goal,
              mode=mode, power_ups=power_ups)
    states = []
    for _ in range(ticks):
        if noise:
            np.random.random(3)
            random.random()
        events = m.tick()
        states.append(json.dumps({**m.snapshot(), "events": events}, sort_keys=True))
        if m.finished:
            break
    return m, states


def played_back(rep):
    _, ticks = replay.play(replay.check(json.loads(json.dumps(rep))))
    out = []
    for state, events in ticks:
        np.random.random(2)  # noise here too
        out.append(json.dumps({**state, "events": events}, sort_keys=True))
    return out


@pytest.mark.parametrize("map_name,mode,power_ups", [
    ("platform", "ffa", False), ("grand", "crown", True), ("classic", "lives", True),
    ("swing", "teams", True), ("ramps", "knockouts", True), ("slider", "ffa", True), ("decks", "lives", False)])
def test_a_replay_is_the_same_match(map_name, mode, power_ups):
    m, states = play_match(map_name, mode, power_ups, goal=1 if mode == "knockouts" else 3)
    rep = replay.record(m, len(states), "ABCD-1", 1_800_000_000)
    assert played_back(rep) == states
    assert len(json.dumps(rep)) < 40_000  # small: inputs only when they change


def test_two_matches_at_once_dont_change_each_other():
    a = Match("platform", [{"kind": "bot:hard", "name": "a"}, {"kind": "bot:hard", "name": "b"}], 3, seed=7)
    b = Match("platform", [{"kind": "bot:hard", "name": "a"}, {"kind": "bot:hard", "name": "b"}], 3, seed=7)
    alone = Match("platform", [{"kind": "bot:hard", "name": "a"}, {"kind": "bot:hard", "name": "b"}], 3, seed=7)
    assert a.snapshot()["players"] == alone.snapshot()["players"]  # same seed, same spawns
    while not a.finished and a.tick_count < 900:
        a.tick()
        b.tick()  # interleaved, like two rooms
    rep = replay.record(a, a.tick_count)
    last = json.loads(played_back(rep)[-1])
    assert last["players"] == a.snapshot()["players"] and last["tick"] == a.tick_count


def test_the_same_seed_is_the_same_match_bots_and_all():
    # Everything random in a match (spawns, the mode, power-ups, the bots'
    # choices) comes from its seed, and nothing else changes it
    slots = [{"kind": "bot:medium", "name": f"b{i}"} for i in range(4)]
    a = Match("grand", slots, 3, mode="crown", power_ups=True, seed=11)
    b = Match("grand", slots, 3, mode="crown", power_ups=True, seed=11)
    for _ in range(600):
        np.random.random(5)
        random.random()
        a.tick()
        random.seed(random.random())
        b.tick()
        assert a.snapshot() == b.snapshot()


def test_matches_leave_the_global_random_numbers_alone():
    np.random.seed(1)
    random.seed(1)
    np_before, py_before = np.random.get_state()[1].copy(), random.getstate()
    m = Match("platform", [{"kind": "bot:hard", "name": "a"}, {"kind": "bot:easy", "name": "b"}], 3, seed=3)
    for _ in range(300):
        m.tick()
    assert (np.random.get_state()[1] == np_before).all() and random.getstate() == py_before


def test_input_codes_round_trip():
    for b in [Buttons(), Buttons(up=True, heavy=True), Buttons(*[True] * 5)]:
        assert input_from_code(input_code(b)) == b
    assert input_from_code(input_code(None)) is None and input_from_code(input_code(np.int64(7))) == 7


def test_bad_files_are_refused():
    m, states = play_match("platform", ticks=100)
    good = json.loads(json.dumps(replay.record(m, len(states))))
    assert replay.check(good)["slots"][0] == {"name": "b0", "kind": "human", "was": "bot:hard", "color": 0, "team": None}
    for change, why in [({"format": "x"}, "not a bonk replay"), ({"v": 9}, "newer"), ({"map": "moon"}, "map"),
                        ({"mode": "golf"}, "mode"), ({"slots": []}, "players"), ({"inputs": [[5, 0, 1], [2, 0, 1]]}, "step"),
                        ({"inputs": [[0, 9, 1]]}, "slot"), ({"inputs": [[0, 0, 999]]}, "input"),
                        ({"ticks": 10 ** 9}, "length"), ({"seed": -1}, "seed"), ({"gravity": 99}, "gravity")]:
        with pytest.raises(replay.BadReplay, match=why):
            replay.check({**good, **change})
    assert "id" not in json.dumps(good["slots"])  # no tokens in a file people share


def test_rooms_keep_the_last_match_and_play_files_back():
    aiohttp = pytest.importorskip("aiohttp")  # noqa: F841
    from aiohttp.test_utils import TestClient, TestServer
    from bonk_game.server import web
    from bonk_game.server.room import RoomManager

    async def go():
        client = TestClient(TestServer(web.make_app(RoomManager())))
        await client.start_server()
        try:
            code = (await (await client.post("/api/rooms")).json())["room"]
            assert (await client.get(f"/api/rooms/{code}/replay")).status == 404  # no match yet
            ws = await client.ws_connect(f"/ws/{code}")
            await ws.send_json({"type": "hello", "name": "Ann", "token": "t", "version": web.VERSION})
            await ws.send_json({"type": "settings", "map": "classic", "bots": ["bot:hard"], "first_to": 1})
            await ws.send_json({"type": "start"})
            seen = []
            while True:
                msg = await asyncio.wait_for(ws.receive_json(), 120)
                if msg["type"] in ("state", "d"):
                    seen.append(msg)
                if msg["type"] == "results":
                    break
            res = await client.get(f"/api/rooms/{code}/replay")
            assert res.status == 200 and "attachment" in res.headers["Content-Disposition"]
            rep = await res.json()
            watched = await client.post("/api/replay", data=json.dumps(rep))
            body = await watched.json()
            bad = await client.post("/api/replay", data="{nope")
            wrong = await client.post("/api/replay", data=json.dumps({**rep, "map": "moon"}))
            await ws.close()
            return msg, rep, seen, body, (bad.status, (await bad.json())["error"]), wrong.status
        finally:
            await client.close()
    results, rep, seen, body, bad, wrong = asyncio.run(go())
    assert results["replay"] is True and rep["match_id"] == results["match_id"]
    assert rep["slots"][0]["kind"] == "human" and rep["slots"][1]["kind"] == "bot:hard"
    assert body["engine"] is True and body["match"]["replay"] is True
    assert [s["kind"] for s in body["match"]["slots"]] == ["human", "bot:hard"]
    # The player's own messages also had their speeds ("you"); otherwise the same
    strip = lambda m: {k: v for k, v in m.items() if k != "you"}
    assert [strip(m) for m in body["states"]] == [strip(m) for m in seen]
    assert bad == (400, "Can't play that file: not a bonk replay.") and wrong == 400
