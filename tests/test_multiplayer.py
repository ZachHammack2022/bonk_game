"""3-4 player free-for-all (issue #12)."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import random

import numpy as np
import pygame
import pytest

from bonk_game.envs.testing_env import PLAYER_KEYS, TestEnv
from bonk_game.envs.utils import arena
from bonk_game.envs.utils.maps import MAPS


def env4(map_name="platform", **kw):
    return TestEnv("ai", "ai", map_name=map_name, more=("ai", "ai"), **kw)


def test_player_count_limits():
    with pytest.raises(ValueError):
        TestEnv("ai", "ai", more=("ai", "ai", "ai"))
    env = env4()
    assert env.n == 4 and len(env.players) == 4
    assert [p.color for p in env.players] == list(arena.PLAYER_COLORS)


def test_observation_is_me_nearest_opponent_and_extras():
    env = env4()
    obs = env.reset()
    n = env.obs_size
    assert obs.shape == (4 * n,)
    P = env.players
    P[0].x, P[0].y = 250, 250
    P[1].x, P[1].y = 450, 250
    P[2].x, P[2].y = 270, 250  # nearest to player 0
    P[3].x, P[3].y = 430, 250  # nearest to player 1
    obs = env._get_obs()
    assert np.allclose(obs[6:12], P[2].get_obs())
    assert np.allclose(obs[n + 6:n + 12], P[3].get_obs())


def test_last_one_standing_takes_the_round():
    env = env4()
    env.reset()
    env.players[0].x = -500  # off the map
    env.step([0] * 4)
    assert env.out == [True, False, False, False] and env.scores == [0, 0, 0, 0]
    env.players[1].x = -500
    env.players[3].x = -500
    env.step([0] * 4)
    assert env.scores == [0, 0, 1, 0]
    assert env.out == [False] * 4  # new round
    assert ("round_over",) in env.events


def test_everyone_left_dying_at_once_all_score():
    env = env4()
    env.reset()
    env.players[0].x = -500
    env.step([0] * 4)
    for i in (1, 2, 3):
        env.players[i].x = -500
    env.step([0] * 4)
    assert env.scores == [0, 1, 1, 1]


def test_out_players_are_frozen_and_ignored():
    env = env4()
    env.reset()
    env.players[0].x = -500
    env.step([0] * 4)
    x = env.players[0].x
    for _ in range(5):
        env.step([0] * 4)
    assert env.players[0].x == x
    assert env.players[0].alive == 0


def test_classic_credits_the_last_toucher():
    env = env4("classic")
    env.reset()
    P = env.players
    env.last_touch[0] = (2, env.steps)
    P[0].x = arena.LEFT
    env.check_collisions()
    assert env.scores[2] == 0 and P[2].score == 1
    # Nobody touched them: nobody scores
    P[1].x = arena.RIGHT
    env.check_collisions()
    assert sum(p.score for p in P) == 1


def test_two_player_classic_still_scores_for_the_other():
    env = TestEnv("ai", "ai", map_name="classic")
    env.reset()
    env.players[0].x = arena.LEFT
    env.check_collisions()
    assert env.players[1].score == 1


@pytest.mark.parametrize("map_name", list(MAPS))
@pytest.mark.parametrize("n", [3, 4])
def test_bot_matches_finish(map_name, n):
    from bonk_game.ui.app import Sim
    random.seed(0)
    np.random.seed(0)
    sim = Sim(map_name, ["bot:hard", "bot:medium", "bot:medium", "bot:easy"][:n], 3)
    for _ in range(40000):
        sim.step()
        if sim.done:
            break
    assert sim.done and max(sim.env.scores) == 3


def test_keys_for_each_player():
    assert len(PLAYER_KEYS) == arena.MAX_PLAYERS
    keys = [k for scheme in PLAYER_KEYS for group in scheme for k in group]
    assert len(keys) == len(set(keys)), "two players share a key"


def test_humans_and_models_mixed():
    class Fixed:
        def predict(self, obs):
            return 0, None
    env = TestEnv("user", "ai", map_name="platform", more=("user", "ai"))
    env.reset()
    pygame.init()
    env.step([0, 3])  # one action per model player, in order


def test_player_setup_adds_and_removes_players():
    from bonk_game.ui.app import App, MatchScene, PlayerSelectScene
    app = App()
    scene = PlayerSelectScene(app, "platform")
    assert scene.n == 2
    scene.focus = scene.count_row
    scene.change(scene.count_row, 1)
    scene.change(scene.count_row, 1)
    assert scene.n == 4 and scene.focus == scene.count_row
    assert scene.options[scene.picks[3]] == "bot:medium"
    scene.change(scene.count_row, 1)  # wraps back to 2
    assert scene.n == 2
    scene.set_count(3)
    scene.start()
    assert isinstance(app.scene, MatchScene) and app.scene.sim.env.n == 3
    for _ in range(120):
        app.scene.update(1 / 60)
    app.scene.draw(app.ui)
