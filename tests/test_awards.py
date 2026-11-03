"""Knockout feed and end-of-match awards (web version)."""
import json

import numpy as np

from bonk_game.envs.testing_env import TestEnv
from bonk_game.server.match import Match, awards, new_stats


def bots(n):
    return [{"kind": "bot:medium", "name": f"bot{i}"} for i in range(n)]


def _drop_out(env, i):
    """Put player i somewhere deadly (well below the map)."""
    p = env.players[i]
    p.x, p.y = env.map.width / 2, env.map.height + 200


def test_a_death_names_whoever_last_hit_them():
    env = TestEnv(None, None, None, map_name="platform")
    env.reset()
    env.last_hit[2] = (0, env.steps)  # player 0 just bumped player 2
    _drop_out(env, 2)
    _, _, info = env.step()
    assert info["kos"] == [(2, 0, False)]


def test_a_fall_with_nobody_near_is_nobodys_knockout():
    env = TestEnv(None, None, None, map_name="platform")
    env.reset()
    env.last_hit[1] = (0, env.steps - env.HIT_CREDIT_STEPS - 5)  # too long ago
    _drop_out(env, 1)
    _, _, info = env.step()
    assert info["kos"] == [(1, None, False)]


def test_awards_pick_the_leaders():
    stats = [new_stats() for _ in range(3)]
    stats[0].update(kos=3, deaths=1, alive=900, best_hit=12.34)
    stats[1].update(kos=1, falls=2, deaths=3, alive=500, best_hit=20)
    stats[2].update(kos=0, deaths=2, alive=700)
    got = {a["id"]: a for a in awards(stats)}
    assert got["kos"]["slots"] == [0] and got["kos"]["value"] == 3
    assert got["hit"]["slots"] == [1] and got["hit"]["value"] == 20
    assert got["falls"]["slots"] == [1]
    assert got["survivor"]["slots"] == [0]


def test_no_award_when_nobody_earned_it_or_everyone_tied():
    stats = [new_stats() for _ in range(2)]
    assert awards(stats) == []
    stats[0]["kos"] = stats[1]["kos"] = 2
    assert "kos" not in {a["id"] for a in awards(stats)}


def test_ties_share_an_award():
    stats = [new_stats() for _ in range(3)]
    stats[0]["kos"] = stats[2]["kos"] = 2
    got = {a["id"]: a for a in awards(stats)}
    assert got["kos"]["slots"] == [0, 2]


def test_a_bot_match_reports_who_knocked_out_whom():
    np.random.seed(1)
    m = Match("platform", bots(4), first_to=2)
    deaths = []
    for _ in range(100_000):
        deaths += [ev for ev in m.tick() if ev["e"] == "death"]
        if m.finished:
            break
    assert deaths and all("by" in d and "wall" in d for d in deaths)
    assert any(d["by"] is not None for d in deaths)
    res = m.results()
    json.dumps(res)
    stats = res["stats"]
    assert sum(s["deaths"] for s in stats) == len(deaths)
    assert sum(s["kos"] for s in stats) == sum(d["by"] is not None for d in deaths)
    assert all(d["by"] != d["i"] for d in deaths)
    assert res["awards"]
