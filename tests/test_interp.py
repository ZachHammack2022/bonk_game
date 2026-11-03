"""Drawing between physics steps (issue #8)."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import random

import numpy as np
import pygame
import pytest

from bonk_game.envs.utils.maps import MAPS
from bonk_game.ui.app import H, W, Sim
from bonk_game.ui.interp import MAX_JUMP


def state(sim):
    env = sim.env
    out = [(p.x, p.y, p.x_v, p.y_v, p.m, p.score) for p in env.players]
    m = env.map
    for body in getattr(m, "bodies", []):
        out.append(tuple(getattr(body, a) for a in ("theta", "omega", "offset", "vx") if hasattr(body, a)))
    for b in getattr(m, "blocks", []):
        out.append(b.rect())
    return out


def run(map_name, draw, steps=600):
    random.seed(1)
    np.random.seed(1)
    sim = Sim(map_name, ["bot", "bot"], 50)
    surface = pygame.Surface((W, H))
    rng = random.Random(9)  # separate RNG so drawing can't touch the bots' one
    for _ in range(steps):
        sim.step()
        if draw:
            for _ in range(2):
                sim.draw(surface, 1.0, alpha=rng.random())
    return state(sim)


@pytest.mark.parametrize("map_name", list(MAPS))
def test_drawing_never_changes_the_physics(map_name):
    assert run(map_name, draw=True) == run(map_name, draw=False)


def test_draws_blended_positions_then_restores_them():
    random.seed(0)
    sim = Sim("platform", ["bot", "bot"], 5)
    p = sim.env.p1
    for _ in range(3):
        sim.step()
    before = (p.x, p.y)
    sim.step()
    after = (p.x, p.y)
    assert before != after
    seen = []
    with sim.interp.blended(0.25):
        seen.append((p.x, p.y))
    assert seen[0] == pytest.approx((before[0] + (after[0] - before[0]) * 0.25,
                                     before[1] + (after[1] - before[1]) * 0.25))
    assert (p.x, p.y) == after


def test_teleports_are_not_blended():
    sim = Sim("classic", ["bot", "bot"], 5)
    sim.step()
    p = sim.env.p1
    p.x += MAX_JUMP + 50  # like a respawn
    with sim.interp.blended(0.5):
        assert p.x == sim.env.p1.x


def test_alpha_one_draws_current_state():
    sim = Sim("swing", ["bot", "bot"], 5)
    for _ in range(5):
        sim.step()
    cur = state(sim)
    with sim.interp.blended(1.0):
        assert state(sim) == cur


def test_new_round_is_not_blended_with_the_old_one():
    sim = Sim("platform", ["bot", "bot"], 5)
    sim.step()
    sim.env.p1.x = -500  # off the map: dies, round resets
    sim.step()
    assert sim.interp.prev is None
