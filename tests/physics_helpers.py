"""Stepping players on a map without a whole env (the physics is the map's
Box2D world: envs/utils/world.py)."""
from bonk_game.envs.utils import stepping


def tick(m, players, time_scale=1.0):
    """One step for `players` on map `m`, as the envs do it: the map's step,
    then who's knocked out (returned, one bool per player), then the move."""
    m.step(move=False)
    dead = [m.killed(p) for p in players]
    for p in players:
        p.doomed = False
    stepping.advance([p for p, d in zip(players, dead) if not d], m, time_scale=time_scale)
    return dead


def deadly_here(m, p):
    """Would the level knock `p` out where it is now?"""
    return m.killed(p)
