"""Fast tests for the game physics. Run with `python -m pytest`.

These only need numpy and pygame, not gymnasium or stable-baselines3.
"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.mechanics import (
    env_collision, env_collision_game, env_collision_gym, player_collision,
)
from bonk_game.envs.testing_env import TestEnv


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


def test_players_spawn_inside_arena_not_touching_anything():
    platforms = arena.make_platforms()
    for _ in range(500):
        p1, p2 = arena.make_players()
        arena.reset_players([p1, p2])
        for p in (p1, p2):
            assert not any(env_collision(p, obj) for obj in platforms)
        assert np.hypot(p1.x - p2.x, p1.y - p2.y) > p1.r + p2.r


def test_floor_bounces_player_back_up():
    floor = arena.make_platforms()[0]
    p, _ = arena.make_players()
    p.x, p.y, p.y_v = 300, arena.BOTTOM - p.r + 2, 10
    env_collision_gym(p, floor)
    assert p.y_v < 0
    assert p.y + p.r < arena.BOTTOM
    assert p.alive


def test_ceiling_bounces_player_back_down():
    ceiling = arena.make_platforms()[3]
    p, _ = arena.make_players()
    p.x, p.y, p.y_v = 300, arena.TOP + p.r - 2, -10
    env_collision_gym(p, ceiling)
    assert p.y_v > 0
    assert p.y - p.r > arena.TOP


def test_wall_kills_in_training_and_scores_in_game():
    left_wall = arena.make_platforms()[1]
    p, _ = arena.make_players()
    p.x, p.y = arena.LEFT + p.r - 2, 300
    env_collision_gym(p, left_wall)
    assert p.alive == 0

    p.x, p.y = arena.LEFT + p.r - 2, 300
    assert env_collision_game(p, left_wall) is True
    assert not env_collision(p, left_wall)  # respawned


def test_collision_conserves_momentum_and_separates_players():
    a, b = arena.make_players()
    a.x, a.y, a.x_v, a.y_v = 300, 300, 5, 0
    b.x, b.y, b.x_v, b.y_v = 335, 300, -5, 0
    b.m = 3
    before = a.m * a.x_v + b.m * b.x_v
    player_collision(a, b)
    after = a.m * a.x_v + b.m * b.x_v
    assert after == pytest.approx(before)
    assert a.x_v < 0  # lighter player bounces back
    assert np.hypot(a.x - b.x, a.y - b.y) == pytest.approx(a.r + b.r)


def test_separating_players_are_not_pulled_back_together():
    a, b = arena.make_players()
    a.x, a.y, a.x_v, a.y_v = 300, 300, -5, 0
    b.x, b.y, b.x_v, b.y_v = 335, 300, 5, 0
    player_collision(a, b)
    assert a.x_v == -5 and b.x_v == 5


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
