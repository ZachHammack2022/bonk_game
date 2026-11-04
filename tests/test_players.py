"""Matches with 2-10 players (issue #12)."""
import math
import random
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils import arena
from bonk_game.envs.utils.controls import Buttons
from bonk_game.envs.utils.maps import MAPS, make_map
from physics_helpers import deadly_here


def no_overlaps(players):
    return all(math.dist((a.x, a.y), (b.x, b.y)) >= a.r + b.r
               for i, a in enumerate(players) for b in players[i + 1:])


@pytest.mark.parametrize("name", list(MAPS))
@pytest.mark.parametrize("n", [2, 5, 10])
def test_every_map_spawns_n_players_apart_and_on_screen(name, n):
    m = make_map(name)
    players = m.make_players(n)
    for seed in range(20):
        np.random.seed(seed)
        m.place_players(players)
        assert no_overlaps(players)
        for p in players:
            assert p.r <= p.x <= m.width - p.r
            assert not deadly_here(m, p), "spawned inside a deadly piece or out of bounds"


def test_player_count_limits():
    m = make_map("platform")
    assert len(m.make_players(10)) == 10
    assert len({p.color for p in m.make_players(10)}) == 10
    for bad in (1, 11):
        with pytest.raises(ValueError):
            m.make_players(bad)


@pytest.mark.parametrize("name", list(MAPS))
def test_every_map_plays_a_ten_player_match(name):
    env = TestEnv(*[None] * 10, map_name=name, winning_score=3)
    obs = env.reset()
    assert obs.shape == (10 * env.obs_size,)
    rng = np.random.default_rng(0)
    done = False
    for _ in range(100_000):
        obs, done, info = env.step(rng.integers(0, 16, size=10))
        assert np.all(np.abs(obs) <= 1)
        if done:
            break
    assert done
    assert max(env.scores) == 3


def test_last_ball_standing_takes_the_round():
    env = TestEnv(None, None, None, map_name="platform")
    env.reset()
    env.players[0].x = -500  # off the map
    _, _, info = env.step()
    assert [d[0] for d in info["deaths"]] == [0]
    assert info["points"] == [] and not info["round_over"]
    assert not env.players[0].alive and env.scores == [0, 0, 0]

    # Out players don't move or collide
    x, y = env.players[0].x, env.players[0].y
    env.step([0, 0, 0])
    assert (env.players[0].x, env.players[0].y) == (x, y)

    env.players[2].x = 900
    _, _, info = env.step()
    assert info["points"] == [1] and info["round_over"]
    assert env.scores == [0, 1, 0]
    assert all(p.alive for p in env.players)  # new round
    assert env.map.steps == 0


def test_everyone_left_dying_at_once_all_score():
    env = TestEnv(None, None, None, map_name="platform")
    env.reset()
    env.players[0].x = -500
    env.step()
    env.players[1].x = -500
    env.players[2].x = 900
    _, _, info = env.step()
    assert sorted(info["points"]) == [1, 2] and info["round_over"]
    assert env.scores == [0, 1, 1]


def put(p, x, y):
    p.x, p.y, p.x_v, p.y_v = x, y, 0, 0


def test_respawn_map_credits_the_last_hitter():
    env = TestEnv(None, None, None, map_name="classic")
    env.reset()
    a, b, c = env.players
    put(a, 300, 300)
    put(b, 300 + a.r + b.r + 2, 300)
    b.x_v = -6  # bumps into a
    put(c, 500, 200)
    env.step()
    assert env.last_hit[0][0] == 1 and env.last_hit[1][0] == 0

    put(a, arena.LEFT, 300)  # into the deadly wall
    deaths, points, round_over = env.check_collisions()
    assert [d[0] for d in deaths] == [0] and points == [1] and not round_over
    assert env.players[1].score == 1 and env.players[2].score == 0


def test_respawn_map_death_without_a_hit_scores_nobody_with_three_players():
    env = TestEnv(None, None, None, map_name="classic")
    env.reset()
    put(env.players[0], arena.LEFT, 300)
    _, points, _ = env.check_collisions()
    assert points == [] and all(p.score == 0 for p in env.players)


def test_old_hits_dont_count():
    env = TestEnv(None, None, None, map_name="classic")
    env.reset()
    env.last_hit[0] = (2, env.steps - env.HIT_CREDIT_STEPS - 1)
    put(env.players[0], arena.LEFT, 300)
    _, points, _ = env.check_collisions()
    assert points == []


def test_two_player_respawn_scoring_is_unchanged():
    env = TestEnv(None, None, map_name="classic")
    env.reset()
    put(env.p1, arena.LEFT, 300)
    env.check_collisions()
    assert env.p2.score == 1


def test_agents_see_their_nearest_opponent():
    env = TestEnv(None, None, None, map_name="classic")
    env.reset()
    a, b, c = env.players
    put(a, 200, 300)
    put(b, 500, 300)
    put(c, 260, 300)
    obs = env._get_obs()
    n, own = env.obs_size, arena.OBS_SIZE // 2
    view = env.view(obs, 0)
    assert np.allclose(view[:own], a.get_obs())
    assert np.allclose(view[own:2 * own], c.get_obs())
    assert np.allclose(env.view(obs, 1)[own:2 * own], c.get_obs())
    assert obs.shape == (3 * n,)


def test_buttons_move_players():
    env = TestEnv(None, None, None, map_name="classic", round_time=0)
    env.reset()
    x = [p.x for p in env.players]
    for _ in range(5):
        env.step([Buttons(right=True), Buttons(left=True), None])
    assert env.players[0].x > x[0] and env.players[1].x < x[1]


def test_wrong_number_of_inputs_is_an_error():
    env = TestEnv(None, None, None)
    env.reset()
    with pytest.raises(ValueError):
        env.step([0, 0])


def test_bot_goes_after_the_nearest_opponent():
    from bonk_game.ui.bot import Bot
    env = TestEnv(None, None, None, map_name="classic")
    env.reset()
    put(env.players[0], 200, 300)
    put(env.players[1], 500, 300)
    put(env.players[2], 260, 300)
    assert Bot(env, 0).them is env.players[2]


# ---------------------------------------------------------------------------
# The game window
# ---------------------------------------------------------------------------
@pytest.fixture
def app():
    from bonk_game.ui.app import App
    return App()


def key(app, k):
    app.scene.event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode=""))


def test_player_select_adds_and_removes_players(app):
    from bonk_game.ui import app as A
    scene = A.PlayerSelectScene(app, "platform")
    app.scene = scene
    scene.focus = scene.COUNT_ROW
    for _ in range(12):
        key(app, pygame.K_RIGHT)
    assert len(scene.picks) == 10
    scene.draw(app.ui)
    for _ in range(12):
        key(app, pygame.K_LEFT)
    assert len(scene.picks) == 2


def test_player_select_allows_one_human(app):
    from bonk_game.ui import app as A
    scene = A.PlayerSelectScene(app, "platform", picks=["human", "bot", "bot"])
    app.scene = scene
    for _ in range(len(scene.options) * 2):
        scene.change(2, 1)
        assert scene.option(2) != "human"
    # Extra humans passed in get turned into Bots
    scene = A.PlayerSelectScene(app, "platform", picks=["human"] * 4)
    assert scene.humans() == [0]


def test_sim_rejects_more_than_one_human():
    from bonk_game.ui.app import Sim
    with pytest.raises(ValueError):
        Sim("platform", ["human", "human"], 5)


def test_wasd_and_arrows_both_work():
    from bonk_game.ui.keys import keyboard_buttons

    class Keys:
        def __init__(self, *ks):
            self.ks = ks

        def __getitem__(self, k):
            return k in self.ks

    assert keyboard_buttons(Keys(pygame.K_a)).left
    assert keyboard_buttons(Keys(pygame.K_LEFT)).left
    assert keyboard_buttons(Keys(pygame.K_UP, pygame.K_SPACE)) == (True, False, False, False, True)
    assert not any(keyboard_buttons(Keys()))


@pytest.mark.parametrize("map_name", ["platform", "classic"])
def test_ten_bot_match_plays_to_results(app, map_name):
    from bonk_game.ui import app as A
    np.random.seed(0)
    random.seed(0)
    picks = ["human"] + ["bot"] * 9
    # (First to 2: with ten balls, first to 3 can take longer than the time
    # below, depending on how the bots' coin flips go)
    scene = A.PlayerSelectScene(app, map_name, picks=picks, first_to=2)
    app.scene = scene
    scene.start()
    assert isinstance(app.scene, A.MatchScene)
    assert app.scene.sim.env.n == 10
    for i in range(60 * 600):
        app.scene.update(1 / 60)
        if i % 30 == 0:
            app.scene.draw(app.ui)
        if isinstance(app.scene, A.ResultsScene):
            break
    assert isinstance(app.scene, A.ResultsScene)
    app.scene.draw(app.ui)
    # "Change players" keeps all ten
    app.scene.menu.activate(1)
    assert len(app.scene.picks) == 10


def respawned(env, i=0):
    """Knock player i into Classic's deadly wall and step: they respawn."""
    put(env.players[i], arena.LEFT, 300)
    env.step()
    return env.players[i]


def test_a_respawned_player_is_held_still_then_plays():
    env = TestEnv(None, None, map_name="classic", round_time=0)
    env.reset()
    p = respawned(env)
    assert p.held == env.RESPAWN_HOLD
    spot = (p.x, p.y)
    for _ in range(env.RESPAWN_HOLD):
        env.step([Buttons(right=True, up=True), None])
        assert (p.x, p.y) == spot  # keys, gravity: nothing moves it
    assert p.held == 0
    env.step([Buttons(right=True), None])
    assert p.x > spot[0]


def test_a_held_player_is_out_of_play():
    env = TestEnv(None, None, None, map_name="classic", round_time=0)
    env.reset()
    a, b, c = env.players
    respawned(env)
    # Nothing hits them...
    put(b, a.x + a.r + b.r - 4, a.y)
    env.check_collisions()
    assert env.last_hit[0] is None and (b.x_v, b.y_v) == (0, 0)
    # ...nothing kills them (they're put back inside the walls)...
    a.x = arena.LEFT
    deaths, _, _ = env.check_collisions()
    assert deaths == [] and a.alive
    # ...and everyone goes after someone else
    put(b, a.x + 40, 300)
    put(c, a.x + 300, 300)
    assert env.nearest_opponent(1) == 2


def test_respawn_hold_can_be_turned_off():
    env = TestEnv(None, None, map_name="classic", respawn_hold=0)
    env.reset()
    assert respawned(env).held == 0


def test_a_new_round_starts_everyone_free():
    env = TestEnv(None, None, None, map_name="classic", round_time=0)
    env.reset()
    respawned(env)
    env.new_round()
    assert all(p.held == 0 for p in env.players)
