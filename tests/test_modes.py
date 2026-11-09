"""Game modes and room settings for the web version."""
import asyncio
import json

import numpy as np
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.server import modes
from bonk_game.server.match import Match
from bonk_game.server.room import Room

GOALS = {"ffa": 2, "teams": 2, "lives": 2, "knockouts": 1, "crown": 10}


def bots(n):
    return [{"kind": "bot:medium", "name": f"bot{i}", "team": i % 2} for i in range(n)]


def play(m, limit=200_000):
    events = []
    for _ in range(limit):
        events += m.tick()
        if m.finished:
            return events
    raise AssertionError("match never finished")


@pytest.mark.parametrize("mode", list(modes.MODES))
@pytest.mark.parametrize("map_name", ["platform", "classic"])
def test_every_mode_plays_to_a_result(mode, map_name):
    np.random.seed(2)
    m = Match(map_name, bots(4), GOALS[mode], mode=mode)
    play(m)
    res = m.results()
    json.dumps(res)
    json.dumps(m.snapshot())
    json.dumps(m.describe())
    assert res["mode"] == mode and len(res["scores"]) == 4


def test_ffa_is_the_default_and_matches_the_env_scores():
    np.random.seed(0)
    m = Match("platform", bots(3), 2)
    play(m)
    assert m.mode.id == "ffa"
    assert m.results()["scores"] == m.env.scores and max(m.env.scores) == 2


# --- teams -----------------------------------------------------------------
def test_teammates_are_not_opponents():
    env = TestEnv(None, None, None, None, map_name="platform", teams=[0, 0, 1, 1])
    env.reset()
    for i in range(4):
        assert env.teams[env.nearest_opponent(i)] != env.teams[i]


def test_bumping_a_teammate_off_is_not_a_knockout():
    env = TestEnv(None, None, None, map_name="platform", teams=[0, 0, 1])
    env.reset()
    env.last_hit[1] = (0, env.steps)
    p = env.players[1]
    p.x, p.y = env.map.width / 2, env.map.height + 200
    _, _, info = env.step()
    assert info["kos"] == [(1, None, False)]


def test_the_last_team_standing_wins_the_round():
    env = TestEnv(None, None, None, map_name="platform", teams=[0, 0, 1])
    env.reset()
    p = env.players[2]
    p.x, p.y = env.map.width / 2, env.map.height + 200
    _, _, info = env.step()
    assert info["round_over"] and sorted(info["points"]) == [0, 1]


def test_teams_match_scores_per_team():
    np.random.seed(3)
    m = Match("platform", bots(4), 2, mode="teams")
    play(m)
    res = m.results()
    assert max(res["team_scores"]) == 2
    assert res["winner_team"] == res["team_scores"].index(2)
    assert m.describe()["slots"][1]["team"] == 1


# --- lives -----------------------------------------------------------------
def test_lives_respawn_until_they_run_out():
    np.random.seed(4)
    m = Match("platform", bots(4), 2, mode="lives")
    events = play(m)
    res = m.results()
    out = [e["i"] for e in events if e["e"] == "eliminated"]
    assert len(out) >= 3 and len(set(out)) == len(out)
    if res["winner"] is not None:
        assert res["scores"][res["winner"]] > 0 and res["winner"] not in out
    for i in out:
        assert not m.env.players[i].alive


# --- knockouts -------------------------------------------------------------
def test_knockouts_go_to_overtime_on_a_tie():
    mode = modes.Knockouts(2, goal=1)
    mode.start(TestEnv(None, None, map_name="platform", respawn=True))
    info = {"kos": [], "points": [], "round_over": False}
    for _ in range(60 * 30 - 1):
        mode.step(info)
    assert mode.step(info) == [{"e": "overtime"}] and not mode.done
    mode.step({**info, "kos": [(0, 1, False)]})
    assert mode.done and mode.winner() == 1


# --- crown -----------------------------------------------------------------
def _crown(n=3):
    env = TestEnv(*[None] * n, map_name="platform", respawn=True, round_time=0)
    env.reset()
    mode = modes.Crown(n, goal=5)
    mode.holder = 0
    mode.start(env)
    return env, mode


def test_bumping_the_wearer_steals_the_crown():
    env, mode = _crown()
    info = {"kos": [], "points": [], "round_over": False}
    for _ in range(40):
        env.steps += 1
        mode.step(info)
    env.last_hit[0] = (2, env.steps)
    assert mode.step(info)[0] == {"e": "crown", "i": 2, "from": 0}
    assert env.focus == 2
    # It can't bounce straight back
    env.last_hit[2] = (0, env.steps)
    assert mode.step(info) == [] and mode.holder == 2


def test_knocking_out_the_wearer_takes_the_crown():
    env, mode = _crown()
    mode.step({"kos": [(0, 1, False)], "points": [], "round_over": False})
    assert mode.holder == 1


def test_holding_the_crown_long_enough_wins():
    env, mode = _crown()
    info = {"kos": [], "points": [], "round_over": False}
    for _ in range(5 * 30):
        mode.step(info)
    assert mode.done and mode.winner() == 0 and mode.scores()[0] == 5


# --- room settings ---------------------------------------------------------
def run(coro):
    return asyncio.run(coro)


async def _room(*names):
    room = Room("TEST")
    sent = {n: [] for n in names}
    for n in names:
        async def send(msg, n=n):
            sent[n].append(msg if isinstance(msg, dict) else json.loads(msg))
        await room.join(n, n, send)
    return room, sent


def test_settings_change_and_are_checked():
    async def go():
        room, sent = await _room("a", "b")
        await room.handle("a", {"type": "settings", "mode": "lives"})
        assert room.settings["mode"] == "lives" and room.settings["first_to"] == 3
        await room.handle("a", {"type": "settings", "round_time": 30, "gravity": "low"})
        assert room.settings["round_time"] == 30 and room.settings["gravity"] == "low"
        await room.handle("a", {"type": "settings", "gravity": "sideways"})
        await room.handle("a", {"type": "settings", "round_time": 7})
        assert room.settings["gravity"] == "low" and room.settings["round_time"] == 30
        # The sinking floor doesn't work with respawning
        await room.handle("a", {"type": "settings", "map": "swing"})
        assert room.settings["map"] != "swing"
        await room.handle("a", {"type": "settings", "mode": "ffa"})
        await room.handle("a", {"type": "settings", "map": "swing"})
        await room.handle("a", {"type": "settings", "mode": "crown"})
        assert room.settings["mode"] == "crown" and room.settings["map"] != "swing"
        # Only the host
        await room.handle("b", {"type": "settings", "mode": "ffa"})
        assert room.settings["mode"] == "crown"
    run(go())


def test_low_gravity_reaches_the_match_and_prediction():
    from bonk_game.envs.utils.world import GRAVITY
    m = Match("platform", bots(2), 2, gravity=0.6)
    assert m.physics()["gravity"] == pytest.approx(0.6 * GRAVITY)
    assert all(p.gravity == pytest.approx(0.6 * GRAVITY) for p in m.env.players)


def test_round_time_setting():
    assert Match("platform", bots(2), 2, round_time=0).env.timer.enabled is False
    assert Match("platform", bots(2), 2, round_time=20).env.timer.limit == 20 * 30
    # Modes with their own clock don't use it
    assert Match("platform", bots(2), 1, mode="knockouts", round_time=20).env.timer.enabled is False


def test_teams_are_balanced_with_team_colours():
    async def go():
        room, sent = await _room("a", "b", "c")
        await room.handle("a", {"type": "settings", "mode": "teams", "bots": ["bot:easy"] * 3})
        await room.handle("b", {"type": "team", "team": 0})
        await room.handle("c", {"type": "team", "team": 0})
        seats = room.lineup()
        teams = [s["team"] for s in seats]
        assert teams.count(0) == 3 and teams.count(1) == 3
        assert seats[1]["team"] == 0 and seats[2]["team"] == 0
        for s in seats:
            assert s["color"] in modes.TEAM_COLORS[s["team"]]
        assert len({s["color"] for s in seats}) == len(seats)
        await room.start()
        assert room.match.mode.id == "teams"
        assert [s["team"] for s in room.match.describe()["slots"]] == teams
        await room.stop()
    run(go())


def test_a_full_team_sends_newcomers_to_the_other():
    async def go():
        names = [f"p{i}" for i in range(7)]
        room, _ = await _room(*names)
        await room.handle("p0", {"type": "settings", "mode": "teams", "map": "grand", "bots": []})
        for n in names:
            await room.handle(n, {"type": "team", "team": 1})
        teams = [s["team"] for s in room.lineup()]
        assert teams.count(1) == modes.TEAM_SIZE and teams.count(0) == 2
    run(go())


def test_respawning_during_sudden_death_lands_between_the_walls():
    env = TestEnv(None, None, None, map_name="platform", respawn=True, round_time=1)
    env.reset()
    env.timer_resets_on_death = False
    env.timer.steps = env.timer.limit + 120  # walls well on their way in
    left, right = env.timer.walls()
    for _ in range(20):
        p = env.players[0]
        p.alive = 1
        p.x, p.y = env.map.width / 2, env.map.height + 200  # falls out
        env.check_collisions()
        assert left < p.x < right


def test_settings_reject_booleans_posing_as_numbers():
    async def go():
        room, sent = await _room("a")
        await room.handle("a", {"type": "settings", "round_time": False})
        await room.handle("a", {"type": "settings", "power_ups": "false"})
        await room.handle("a", {"type": "team", "team": True})
        assert room.settings["round_time"] is None and room.settings["power_ups"] is False
        assert room.members["a"].team is None
    run(go())


def test_the_browser_is_told_who_is_held_after_a_respawn():
    m = Match("platform", bots(3), 2, mode="knockouts", seed=4)
    assert m.describe()["respawn_hold"] == 2
    seen = None
    for _ in range(20_000):
        m.tick()
        s = m.snapshot()
        if "held" in s:
            seen = s
            break
    assert seen is not None, "nobody respawned"
    held = [i for i, h in enumerate(seen["held"]) if h]
    assert held and all(0 < seen["held"][i] <= 2 for i in held)
    assert all(m.env.players[i].held for i in held)
