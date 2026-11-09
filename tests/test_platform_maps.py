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


def run_into_the_right_post(m, a, seconds):
    """Hold right from the middle for `seconds`; then let go. Returns the
    step `a` was knocked out on (or None) and how far out the right half
    got."""
    place(a, m.CENTER + 60, m.TOP - a.r - 1)
    died, furthest = None, 0
    for t in range(30 * 5):
        if t < 30 * seconds and died is None:
            a.move_right(a.push)
        if died is None and tick(m, [a])[0]:
            died = t
            a.dies()
        elif died is not None:
            m.step()
        furthest = max(furthest, m.halves[1].offset)
    return died, furthest


def test_running_into_a_post_shoves_that_half_out_and_you_with_it():
    m = make_map("slider")
    a, _ = m.make_players()
    died, furthest = run_into_the_right_post(m, a, 3)
    assert died is not None and a.x > m.width  # went out over the right-hand edge
    assert furthest > 60
    assert m.halves[0].offset == 0  # the other half didn't move
    # ...and the half came back home on its own, and stopped there
    assert m.halves[1].offset == pytest.approx(0, abs=0.5) and m.halves[1].vx == pytest.approx(0, abs=0.1)


def test_a_half_comes_home_and_only_slides_outward():
    m = make_map("slider")
    left, right = m.halves
    left.vx, right.vx = -14, -14  # left half out, right half in
    for _ in range(8):
        m.step()
    assert left.offset < -40 and right.offset == pytest.approx(0, abs=0.5)
    for _ in range(60):
        m.step()
        assert left.offset <= 0.5  # (never past home)
    assert left.offset == pytest.approx(0, abs=0.5) and left.vx == pytest.approx(0, abs=0.1)


def test_a_half_is_feather_light():
    """Any ball moves it nearly at its own speed; a heavy one a bit more so."""
    def slam(mass):
        m = make_map("slider")
        a, _ = m.make_players()
        post = m.halves[1].blocks[2]
        place(a, post.cx - 30, post.cy + 10)
        a.x_v, a.m = 12, mass
        a.gravity = 0
        for _ in range(4):
            tick(m, [a])
        return m.halves[1].vx

    light, heavy = slam(1), slam(5)
    assert light > 6 and heavy > light


def test_slider_resets_between_rounds():
    m = make_map("slider")
    m.halves[0].vx, m.halves[1].vx = -8, 8
    for _ in range(5):
        m.step()
    assert m.halves[0].offset < 0 < m.halves[1].offset
    m.reset()
    assert all(h.offset == 0 and h.vx == 0 for h in m.halves)
    assert m.halves[1].blocks[1].x1 == m.CENTER + m.HALF_WIDTH + 2


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
