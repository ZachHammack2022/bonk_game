"""Power-ups (web version, a room setting)."""
import json
import random

import numpy as np
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils.controls import Buttons
from bonk_game.server import powerups as pu
from bonk_game.server.match import Match

NOTHING = {"kos": [], "points": [], "round_over": False, "deaths": []}


def setup(n=2, map_name="classic"):
    env = TestEnv(*[None] * n, map_name=map_name)
    env.reset()
    return env, pu.PowerUps(env, random.Random(0))


def give(env, ups, i, kind):
    """Put a pickup on player i and let them grab it."""
    p = env.players[i]
    ups.pickups = [[p.x, p.y, kind]]
    events = ups.step(NOTHING)
    assert events[0]["e"] == "pickup" and events[0]["i"] == i
    ups.apply()


def test_pickups_appear_in_the_spawn_area():
    env, ups = setup()
    events = []
    for _ in range(int(pu.FIRST_SPAWN * 30) + 1):
        events += ups.step(NOTHING)
    spawns = [e for e in events if e["e"] == "spawn"]
    assert len(spawns) == 1
    left, right, top, bottom = env.map.spawn_box
    x, y, kind = ups.pickups[0]
    assert left <= x <= right and top <= y <= bottom and kind in pu.KINDS
    json.dumps(ups.state())


def test_never_more_than_a_few_at_once():
    env, ups = setup()
    for p in env.players:
        p.alive = 0  # nobody picks anything up
    for _ in range(30 * 60):
        ups.step(NOTHING)
    assert len(ups.pickups) == pu.MAX_ON_MAP


def test_speed_pushes_harder():
    env, ups = setup()
    give(env, ups, 0, "speed")
    a, b = env.players
    a.x_v = b.x_v = 0
    a.move_right(2)
    b.move_right(2)
    assert a.x_v == pytest.approx(b.x_v * pu.KINDS["speed"]["force"])
    assert a.v_range > b.v_range


def test_float_and_iron():
    env, ups = setup()
    give(env, ups, 0, "float")
    assert env.players[0].gravity < env.players[1].gravity
    give(env, ups, 1, "iron")
    p = env.players[1]
    assert p.m == p.max_m
    p.x_v = 0
    p.move_right(2)
    assert p.x_v == pytest.approx(2 / p.min_m)  # heavy, but moves like a light ball


def test_punch_sends_the_next_player_flying_once():
    env, ups = setup()
    give(env, ups, 0, "punch")
    a, b = env.players
    b.x, b.y = a.x + 30, a.y
    env.steps += 1
    env.last_hit[0] = (1, env.steps)
    events = ups.step(NOTHING)
    assert [e["e"] for e in events] == ["punch"]
    assert b.x_v == pytest.approx(pu.PUNCH_SPEED)
    assert ups.effects[0] is None


def test_effects_run_out_and_end_on_a_knockout():
    env, ups = setup()
    give(env, ups, 0, "speed")
    for _ in range(pu.KINDS["speed"]["seconds"] * 30):
        ups.step(NOTHING)
    assert ups.effects[0] is None
    give(env, ups, 1, "float")
    ups.step({**NOTHING, "kos": [(1, None, False)]})
    assert ups.effects[1] is None
    ups.apply()
    assert env.players[1].gravity == pytest.approx(1.5)


def test_a_new_round_clears_everything():
    env, ups = setup(map_name="platform")
    give(env, ups, 0, "iron")
    ups.pickups = [[100, 100, "speed"]]
    ups.step({**NOTHING, "round_over": True})
    assert ups.pickups == [] and ups.effects == [None, None]


@pytest.mark.parametrize("mode", ["ffa", "knockouts"])
def test_a_match_with_power_ups(mode):
    np.random.seed(5)
    m = Match("platform", [{"kind": "bot:medium", "name": f"b{i}"} for i in range(4)],
              2 if mode == "ffa" else 1, mode=mode, power_ups=True)
    seen = set()
    for _ in range(200_000):
        seen |= {e["e"] for e in m.tick()}
        if m.finished:
            break
    assert m.finished and "spawn" in seen
    res = m.results()
    json.dumps(res)
    json.dumps(m.snapshot())
    assert m.describe()["powerups"]["speed"]["force"] > 1


def test_off_by_default():
    m = Match("platform", [{"kind": "bot:medium", "name": "a"}, {"kind": "bot:medium", "name": "b"}], 2)
    assert m.powerups is None and "pickups" not in m.snapshot()
    assert m.describe()["powerups"] is None
    # Humans' buttons still work as before
    m.set_input(0, Buttons(right=True))
