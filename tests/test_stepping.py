"""Physics substeps (envs/utils/stepping.py): players and moving parts move
in pieces with collisions in between."""
import numpy as np
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils import stepping
from bonk_game.envs.utils.controls import Buttons
from bonk_game.envs.utils.maps import make_map

RIGHT = Buttons(False, False, False, True, False)


def env_on(map_name, n=2):
    env = TestEnv(*["human"] * n, map_name=map_name)
    env.reset()
    env.timer.limit = 0  # no sudden death
    return env


@pytest.mark.parametrize("speed", [10, 20, 28])
def test_balls_closing_at_full_speed_bounce_instead_of_passing_through(speed):
    env = env_on("platform")
    a, b = env.players
    a.x, a.y, b.x, b.y = 300, 200, 345, 200
    a.x_v, b.x_v, a.y_v, b.y_v = speed, -speed, 0, 0
    env.step()
    env.step()
    assert a.x < b.x and a.x_v < 0 < b.x_v


def test_pushing_a_ball_is_a_steady_shove_not_a_launch():
    env = env_on("platform")
    a, b = env.players
    a.x, a.y, b.x, b.y = 250, 270, 291, 270
    gaps = []
    for _ in range(40):
        env.step([RIGHT, None])
        gaps.append(b.x - a.x)
    assert np.std(gaps[10:]) < 3


def test_a_ball_rides_a_fast_sliding_platform():
    env = env_on("slider")
    a, b = env.players
    plat = env.map.platform  # (the right half of the ring)
    corner = plat.blocks[1]
    top = corner.y1
    a.x, a.y, b.x, b.y = (corner.x1 + corner.x2) / 2, top - 21, 300, top - 21
    for _ in range(10):
        env.step()
    gaps = []
    # (Short moves: the ring's halves have no grip, so a long one slides the
    # block out from under the ball. What matters is that it stays on top.)
    for t in range(40):
        plat.vx = 12 if (t // 3) % 2 == 0 else -12
        env.step()
        gaps.append(corner.y1 - (a.y + a.r))
    assert a.alive and max(abs(g) for g in gaps) < 2


def test_moving_parts_move_the_same_in_substeps_or_whole_steps():
    whole, split = make_map("slider"), make_map("slider")
    whole.platform.vx = split.platform.vx = 9
    for _ in range(8):  # (out and still on its way: it's pulled home after)
        whole.step()
        split.step(move=False)
        for _ in range(stepping.SUBSTEPS):
            split.move(1 / stepping.SUBSTEPS)
    assert split.platform.offset == pytest.approx(whole.platform.offset, rel=0.02)

    whole, split = make_map("swing"), make_map("swing")
    whole.swing.omega = split.swing.omega = 0.08
    for _ in range(30):
        whole.step()
        split.step(move=False)
        for _ in range(stepping.SUBSTEPS):
            split.move(1 / stepping.SUBSTEPS)
    assert split.swing.theta == pytest.approx(whole.swing.theta, abs=0.02)
    assert split.sink == pytest.approx(whole.sink)


def test_touching_something_deadly_between_checks_still_kills():
    env = env_on("classic")
    a, b = env.players
    a.doomed = True
    _, _, info = env.step()
    assert [d[0] for d in info["deaths"]] == [0]


def test_the_same_inputs_give_the_same_match():
    def run():
        env = TestEnv("bot:medium", "bot:medium", map_name="swing", seed=7)
        import random

        from bonk_game.ui.bot import Bot
        bots = [Bot(env, i, "medium", rng=random.Random(i)) for i in range(2)]
        obs = env.reset()
        for _ in range(300):
            obs, done, _ = env.step([bots[i].predict(obs)[0] for i in range(2)])
        return obs

    np.testing.assert_array_equal(run(), run())


def test_the_client_is_told_the_substeps():
    from bonk_game.server.match import Match
    m = Match("platform", [{"kind": "human", "name": "a"}, {"kind": "human", "name": "b"}], 5)
    assert m.physics()["substeps"] == stepping.SUBSTEPS
