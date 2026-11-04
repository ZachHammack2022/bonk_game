"""Fast tests for the game physics. Run with `python -m pytest`.

These only need numpy and pygame, not gymnasium or stable-baselines3.
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.maps import make_map
from bonk_game.envs.utils.world import PLAYER_BOUNCE, World
from bonk_game.envs.testing_env import TestEnv
from physics_helpers import deadly_here, tick


@pytest.fixture(autouse=True)
def seeded():
    np.random.seed(0)


def test_action_table_covers_every_direction_with_and_without_heavy():
    assert sorted(arena.ACTIONS) == list(range(16))
    moves = {(int(dx), int(dy), int(h)) for dx, dy, h in arena.ACTIONS.values()}
    # 8 directions x {light, heavy}, no duplicates
    assert len(moves) == 16
    assert sum(h for _, _, h in moves) == 8
    assert (-1, -1, 0) in moves  # up-left without going heavy


def overlaps(p, block):
    qx = min(max(p.x, block.x1), block.x2)
    qy = min(max(p.y, block.y1), block.y2)
    return np.hypot(p.x - qx, p.y - qy) <= p.r


def test_players_spawn_inside_arena_not_touching_anything():
    platforms = arena.make_platforms()
    for _ in range(500):
        p1, p2 = arena.make_players()
        arena.reset_players([p1, p2])
        for p in (p1, p2):
            assert not any(overlaps(p, obj) for obj in platforms)
        assert np.hypot(p1.x - p2.x, p1.y - p2.y) > p1.r + p2.r


def test_floor_bounces_player_back_up():
    m = make_map("classic")
    p, _ = m.make_players()
    p.x, p.y, p.x_v, p.y_v = 300, arena.BOTTOM - p.r - 5, 0, 10
    for _ in range(2):
        tick(m, [p])
    assert p.y_v < -5  # most of the speed comes back (Classic's floor is bouncy)
    assert p.y + p.r < arena.BOTTOM + 1
    assert p.alive


def test_ceiling_bounces_player_back_down():
    m = make_map("classic")
    p, _ = m.make_players()
    p.x, p.y, p.x_v, p.y_v = 300, arena.TOP + p.r + 5, 0, -10
    for _ in range(2):
        tick(m, [p])
    assert p.y_v > 0
    assert p.y - p.r > arena.TOP - 1


def test_side_walls_are_deadly():
    m = make_map("classic")
    p, _ = m.make_players()
    p.x, p.y, p.x_v, p.y_v = arena.LEFT + p.r + 4, 300, -10, 0
    assert tick(m, [p]) == [False]
    assert tick(m, [p]) == [True]
    p.x, p.y = 300, 300
    assert not deadly_here(m, p)


def free_balls():
    """Two balls in empty space with no gravity."""
    w = World()
    a, b = arena.make_players()
    for p in (a, b):
        p.gravity = 0
    return w, a, b


def test_collision_conserves_momentum_and_separates_players():
    w, a, b = free_balls()
    a.x, a.y, a.x_v, a.y_v = 300, 300, 5, 0
    b.x, b.y, b.x_v, b.y_v = 345, 300, -5, 0
    b.m = 3
    before = a.m * a.x_v + b.m * b.x_v
    contacts = []
    w.step([a, b], on_contact=lambda i, j: contacts.append((i, j)))
    after = a.m * a.x_v + b.m * b.x_v
    assert contacts and contacts[0] == (0, 1)
    assert after == pytest.approx(before, rel=0.01)
    assert a.x_v < 0  # lighter player bounces back
    assert np.hypot(a.x - b.x, a.y - b.y) >= a.r + b.r - 0.5
    # They part at PLAYER_BOUNCE of the speed they met at
    assert b.x_v - a.x_v == pytest.approx(PLAYER_BOUNCE * 10, abs=0.01)


def test_separating_players_are_not_pulled_back_together():
    w, a, b = free_balls()
    a.x, a.y, a.x_v, a.y_v = 300, 300, -5, 0
    b.x, b.y, b.x_v, b.y_v = 339, 300, 5, 0
    w.step([a, b])
    assert a.x_v == pytest.approx(-5, abs=1e-3) and b.x_v == pytest.approx(5, abs=1e-3)


def test_heavy_wears_off_and_can_be_reused():
    p, _ = arena.make_players()
    p.make_heavy()
    assert p.m == p.max_m
    for _ in range(100):
        p.update_mass()
    assert p.m == p.min_m
    p.make_heavy()
    assert p.m == p.max_m


def test_observations_stay_in_bounds():
    env = TestEnv(None, None)
    obs = env.reset()
    rng = np.random.default_rng(0)
    for _ in range(2000):
        obs, done, _ = env.step(rng.integers(0, 16, size=2))
        assert obs.shape == (24,)
        assert np.all(obs >= -1) and np.all(obs <= 1)
        if done:
            break


def test_match_ends_at_winning_score():
    env = TestEnv(None, None, winning_score=3)
    env.reset()
    for _ in range(100_000):
        # Both players hold "right": someone hits the wall a lot
        _, done, _ = env.step([0, 0])
        if done:
            break
    assert done
    assert max(env.scores) == 3


def test_training_env_episode_runs_and_ends_with_valid_reward():
    pytest.importorskip("gymnasium")
    from bonk_game.envs.training_env import BonkEnv
    env = BonkEnv(opponent_path=None)
    obs, _ = env.reset(seed=1)
    assert env.observation_space.contains(obs)
    done = False
    for _ in range(5000):
        obs, reward, done, _, info = env.step(env.action_space.sample())
        assert env.observation_space.contains(obs)
        if done:
            assert reward in (-1.0, 0.0, 1.0)
            break
    assert done


def test_rgb_render():
    env = TestEnv(None, None, render_mode="rgb_array")
    env.reset()
    frame = env.render()
    assert frame.shape == (arena.HEIGHT, arena.WIDTH, 3)
    env.close()


def test_envs_have_their_own_random_numbers():
    from bonk_game.envs.testing_env import TestEnv
    a, b = TestEnv("human", "human", "human", seed=4), TestEnv("human", "human", "human", seed=4)
    np.random.random(10)  # (doesn't change anything)
    assert np.array_equal(a.reset(), b.reset())
    for _ in range(100):
        a.step(), b.step()
    assert [(p.x, p.y) for p in a.players] == [(p.x, p.y) for p in b.players]
    # The training env: reset(seed=) decides where players spawn
    pytest.importorskip("gymnasium")
    from bonk_game.envs.training_env import BonkEnv
    env = BonkEnv(map_name="platform", opponent_path=None)
    first, _ = env.reset(seed=9)
    np.random.random(10)
    again, _ = env.reset(seed=9)
    assert np.array_equal(first, again)
