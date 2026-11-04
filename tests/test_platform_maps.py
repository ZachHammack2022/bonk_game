"""Tests for the Floating Platform and Sliding Platform maps."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils.maps import MAPS, make_map
from physics_helpers import tick


@pytest.fixture(autouse=True)
def seeded():
    np.random.seed(0)


def place(p, x, y):
    p.x, p.y, p.x_v, p.y_v = x, y, 0, 0


@pytest.mark.parametrize("name", ["platform", "slider"])
def test_players_can_stand_still_without_anything_moving(name):
    m = make_map(name)
    a, b = m.make_players()
    place(a, 300, m.TOP - a.r - 1)
    place(b, 400, m.TOP - b.r - 1)
    for _ in range(300):
        assert not any(tick(m, [a, b]))
    assert abs(a.y - (m.TOP - a.r)) < 3
    if name == "slider":
        assert m.platform.offset == pytest.approx(0)


def test_pushing_the_opponent_off_the_platform_kills_them():
    m = make_map("platform")
    a, b = m.make_players()
    place(a, 300, m.TOP - a.r - 1)
    place(b, 360, m.TOP - b.r - 1)
    for _ in range(600):
        # Push until they're over the edge, then brake
        (a.move_right if b.x < m.RIGHT else a.move_left)(a.push)
        dead = tick(m, [a, b])
        if any(dead):
            break
    assert dead == [False, True]


def test_jumping_over_a_slider_post_drops_you_off_the_edge():
    m = make_map("slider")
    p, _ = m.make_players()
    place(p, m.RIGHT - 60, m.TOP - p.r - 1)
    died = False
    for _ in range(300):
        p.move_right(1)
        if p.grounded:
            p.move_up(2)
        if tick(m, [p])[0]:
            died = True
            break
    assert died
    assert p.x > m.RIGHT  # went out over the right-hand edge


def test_slider_moves_when_pushed_and_stays_on_its_rail():
    m = make_map("slider")
    a, _ = m.make_players()
    place(a, 260, m.TOP - a.r - 1)
    for _ in range(200):
        a.move_right(2)
        tick(m, [a])
        assert abs(m.platform.offset) <= m.TRAVEL + 0.5  # (Box2D's joint limits give a hair)
    assert m.platform.offset > 50  # player shoved it right


def test_heavy_hits_push_the_slider_harder():
    def slam(mass):
        m = make_map("slider")
        a, _ = m.make_players()
        place(a, m.LEFT - a.r - 5, m.TOP - 25)
        a.x_v, a.m = 12, mass
        for _ in range(5):
            tick(m, [a])
        return m.platform.vx

    light, heavy = slam(1), slam(5)
    assert light > 0
    assert heavy > 2 * light


def test_slider_resets_between_rounds():
    m = make_map("slider")
    m.platform.vx = 8
    for _ in range(10):
        m.step()
    assert m.platform.offset != 0
    m.reset()
    assert m.platform.offset == 0 and m.platform.vx == 0
    assert m.platform.blocks[0].x1 == m.LEFT


@pytest.mark.parametrize("name", list(MAPS))
def test_every_map_plays_a_full_match_with_valid_observations(name):
    env = TestEnv(None, None, map_name=name, winning_score=3)
    obs = env.reset()
    assert obs.shape == (2 * env.obs_size,)
    rng = np.random.default_rng(0)
    done = False
    for _ in range(100_000):
        obs, done, _ = env.step(rng.integers(0, 16, size=2))
        assert np.all(np.abs(obs) <= 1)
        if done:
            break
    assert done


@pytest.mark.parametrize("name", list(MAPS))
def test_every_map_has_a_training_env(name):
    pytest.importorskip("gymnasium")
    from bonk_game.envs.training_env import BonkEnv
    env = BonkEnv(map_name=name, opponent_path=None)
    obs, _ = env.reset(seed=3)
    env.action_space.seed(3)
    assert env.observation_space.contains(obs)
    for t in range(15000):
        # Random actions, each held a while (pushes are gentle on the open
        # maps: flicking between keys every step goes nowhere)
        if t % 20 == 0:
            action = env.action_space.sample()
        obs, reward, done, _, _ = env.step(action)
        assert env.observation_space.contains(obs)
        if done:
            break
    assert done
