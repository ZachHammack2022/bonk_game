"""Headless smoke tests for the game window: every screen draws, a full
bot-vs-bot match runs to the results screen, and the bot is sane."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame
import pytest

from bonk_game.envs.utils.maps import MAPS


@pytest.fixture
def app():
    from bonk_game.ui.app import App
    return App()


def key(app, k):
    app.scene.event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode=""))


def tick(app, seconds):
    for _ in range(int(seconds * 60)):
        app.scene.update(1 / 60)
    app.scene.draw(app.ui)


def test_menu_flow_reaches_a_match(app):
    from bonk_game.ui import app as A
    tick(app, 0.5)
    assert isinstance(app.scene, A.TitleScene)
    key(app, pygame.K_RETURN)  # Play
    assert isinstance(app.scene, A.MapSelectScene)
    tick(app, 0.1)
    key(app, pygame.K_RETURN)  # first map
    assert isinstance(app.scene, A.PlayerSelectScene)
    tick(app, 0.1)
    key(app, pygame.K_RETURN)  # start
    assert isinstance(app.scene, A.MatchScene)
    tick(app, 2)
    assert app.scene.phase in ("play", "scored")  # the bot may already have scored
    key(app, pygame.K_ESCAPE)
    assert app.scene.paused
    tick(app, 0.2)
    key(app, pygame.K_ESCAPE)
    assert not app.scene.paused


def test_how_to_play_and_back(app):
    from bonk_game.ui import app as A
    key(app, pygame.K_LEFT)  # focus "How to play"
    key(app, pygame.K_RETURN)
    assert isinstance(app.scene, A.HowToScene)
    tick(app, 0.1)
    key(app, pygame.K_ESCAPE)
    assert isinstance(app.scene, A.TitleScene)


@pytest.mark.parametrize("map_name", list(MAPS))
def test_bot_match_plays_to_results(app, map_name):
    from bonk_game.ui import app as A
    np.random.seed(0)
    app.go(A.MatchScene(app, map_name, ["bot", "bot"], ["bot", "bot"], 2))
    for _ in range(60 * 240):
        app.scene.update(1 / 60)
        if isinstance(app.scene, A.ResultsScene):
            break
    assert isinstance(app.scene, A.ResultsScene)
    tick(app, 0.5)
    key(app, pygame.K_RETURN)  # rematch
    assert isinstance(app.scene, A.MatchScene)


def test_sounds_synthesize():
    from bonk_game.ui.sound import _build
    for name, wave in _build().items():
        assert len(wave) > 100, name
        assert np.max(np.abs(wave)) <= 1.0, name


def test_bot_beats_a_player_who_does_nothing():
    from bonk_game.envs.testing_env import TestEnv
    from bonk_game.ui.bot import Bot
    np.random.seed(0)
    env = TestEnv("user", "ai", map_name="platform", winning_score=3)
    bot = Bot(env, 1)
    env.reset()
    for _ in range(20000):
        # Player 1 is "human" but presses nothing
        _, done, _ = env.step(bot.think())
        if done:
            break
    assert env.scores[1] == 3


def test_map_select_scrolls_to_every_map(app):
    from bonk_game.ui import app as A
    scene = A.MapSelectScene(app)
    app.scene = scene
    for i in range(len(scene.names) - 1):
        key(app, pygame.K_TAB)
        tick(app, 0.4)
        x, y = scene.card_pos(scene.focus)
        top, bottom = scene.VIEW
        assert top - 4 <= y and y + scene.CARD_H <= bottom, scene.names[scene.focus]
    assert scene.focus == len(scene.names) - 1
    key(app, pygame.K_TAB)  # wraps to the first map
    tick(app, 0.6)
    assert scene.focus == 0 and scene.scroll == 0
