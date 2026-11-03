"""Tests for the Sinking Swing map."""
import math
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils.maps import MAPS, SwingMap, agent_dir, env_id, make_map


@pytest.fixture(autouse=True)
def seeded():
    np.random.seed(0)


def simulate(m, p, steps, control=None):
    """Step one player on a map. Returns the step it died on, or None."""
    for t in range(steps):
        if control:
            control(t, p)
        m.step()
        if m.collide(p):
            return t
        p.update()
    return None


def place(p, x, y):
    p.x, p.y, p.x_v, p.y_v = x, y, 0, 0


def test_maps_are_registered_with_their_own_env_and_agent_folder():
    assert set(MAPS) >= {"classic", "swing"}
    assert env_id("classic") == "bonk_game/bonk-v0"  # unchanged for old agents
    assert env_id("swing") == "bonk_game/bonk-swing-v0"
    assert agent_dir("classic") == "./agents"
    assert agent_dir("swing") == "./agents/swing"
    with pytest.raises(ValueError):
        make_map("nope")


def test_floor_holds_players_then_sinks_away_and_kills_them():
    m = make_map("swing")
    p, _ = m.make_players()
    place(p, 200, m.FLOOR_Y - p.r - 1)
    assert simulate(m, p, m.SINK_DELAY) is None  # safe during the grace period
    assert p.y < m.FLOOR_Y
    died = simulate(m, p, 2000)
    assert died is not None
    assert p.y - p.r > m.height  # fell off the bottom


def test_swing_is_a_safe_spot_after_the_floor_is_gone():
    m = make_map("swing")
    p, _ = m.make_players()
    sx, sy = m.swing.seat_pos()
    place(p, sx, sy - p.r - 1)
    assert simulate(m, p, 2000) is None
    assert m.sink > m.height - m.FLOOR_Y  # floor is off screen
    assert math.dist((p.x, p.y), m.swing.seat_pos()) < 2 * p.r


def test_rider_stays_in_a_big_swing():
    m = make_map("swing")
    p, _ = m.make_players()
    m.swing.theta = 0.6
    sx, sy = m.swing.seat_pos()
    place(p, sx, sy - p.r - 1)
    assert simulate(m, p, 600) is None
    assert math.dist((p.x, p.y), m.swing.seat_pos()) < 2 * p.r


def test_launch_pad_fires_players_out_of_the_pit():
    m = make_map("swing")
    p, _ = m.make_players()
    place(p, (m.HOLE_LEFT + m.HOLE_RIGHT) / 2, m.FLOOR_Y + 30)
    lowest_y = p.y
    for _ in range(40):
        m.step()
        m.collide(p)
        p.update()
        lowest_y = min(lowest_y, p.y)
    assert lowest_y < m.FLOOR_Y - 80


def test_heavy_players_kick_the_swing_harder():
    def kick(mass):
        m = make_map("swing")
        p, _ = m.make_players()
        sx, sy = m.swing.seat_pos()
        place(p, sx - m.swing.seat_width / 2 - p.r + 2, sy - 5)
        p.x_v, p.m = 15, mass
        m.collide(p)
        return m.swing.omega

    light, heavy = kick(1), kick(5)
    assert light > 0
    assert heavy > 2 * light


def test_up_is_a_jump_not_flight():
    m = make_map("swing")
    p, _ = m.make_players()
    place(p, 200, m.FLOOR_Y - p.r - 1)
    heights = []
    for _ in range(120):
        p.move_up(2)
        m.step()
        m.collide(p)
        p.update()
        heights.append(p.y)
    # Jumps go up but always come back down to the floor
    assert min(heights) < m.FLOOR_Y - 150
    assert max(heights[60:]) > m.FLOOR_Y - p.r - 5

    # Mid-air "up" does nothing
    place(p, 200, 200)
    p.grounded = False
    p.move_up(2)
    assert p.y_v == 0


def test_a_player_can_jump_into_the_swing():
    m = make_map("swing")
    p, _ = m.make_players()
    place(p, 180, m.FLOOR_Y - p.r - 1)

    def climb(t, p):
        sx, sy = m.swing.seat_pos()
        target = sx - 110
        if p.y > sy and p.grounded and abs(p.x - target) < 15:
            p.move_up(2)
        elif p.y > sy + 20 and p.grounded:
            (p.move_right if p.x < target else p.move_left)(1)
        else:
            if p.x < sx - 3 and p.x_v < 4:
                p.move_right(1)
            if p.x > sx + 3 and p.x_v > -4:
                p.move_left(1)

    assert simulate(m, p, 1500, climb) is None
    assert math.dist((p.x, p.y), m.swing.seat_pos()) < 2 * p.r


@pytest.mark.parametrize("x, y", [(-60, 300), (740, 300), (300, SwingMap.KILL_TOP - 5)])
def test_leaving_the_screen_kills(x, y):
    m = make_map("swing")
    p, _ = m.make_players()
    place(p, x, y)
    assert m.collide(p)


def test_swing_match_resets_the_round_on_each_kill():
    env = TestEnv(None, None, map_name="swing", winning_score=3)
    obs = env.reset()
    assert obs.shape == (2 * env.obs_size,)
    assert env.obs_size == 15
    rng = np.random.default_rng(0)
    done = False
    for _ in range(50_000):
        before = list(env.scores)
        obs, done, _ = env.step(rng.integers(0, 16, size=2))
        assert np.all(np.abs(obs) <= 1)
        if env.scores != before:
            assert env.map.steps == 0  # the map restarted
        if done:
            break
    assert done
    assert max(env.scores) >= 3


def test_swing_training_env():
    pytest.importorskip("gym")
    from bonk_game.envs.training_env import BonkEnv
    env = BonkEnv(map_name="swing", opponent_path=None)
    obs = env.reset(seed=2)
    assert obs.shape == env.observation_space.shape == (15,)
    done = False
    for _ in range(15000):
        obs, reward, done, _ = env.step(env.action_space.sample())
        assert env.observation_space.contains(obs)
        if done:
            break
    assert done


def test_agent_up_actions_jump_on_jump_maps():
    from bonk_game.envs.utils import arena
    m = make_map("swing")
    p, _ = m.make_players()
    place(p, 200, m.FLOOR_Y - p.r + 1)  # resting on the floor
    m.collide(p)
    assert p.grounded
    arena.apply_action(p, 3)  # up
    assert p.y_v == -m.jump_speed
