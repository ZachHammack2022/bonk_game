"""Moving players through a step in substeps.

A step is 1/30 s (what agents, the network and replays count in). Players
used to move a whole step at once, with collisions checked once per step:
at up to 28 px a step, two balls (40 px across together) closing at full
speed could pass straight through each other, and a pile of balls on a
floor jostled for several steps before settling.

Now each step's movement is split into SUBSTEPS pieces, with the level and
the other players collided in between. The level's moving parts (the swing,
sliding platforms, a sinking floor) move in the same substeps, so riding or
being hit by them is just as smooth. Nothing moves more than ~7 px between
collision checks, so nothing tunnels, contacts resolve within the step they
happen, and gravity, bounces and pushes come out smoother and more accurate.

A step, for the players still in play:

    collide (by the env: deaths, scoring, player contacts)
    begin_step (jumping)
    integrate 1/SUBSTEPS, collide, integrate 1/SUBSTEPS, collide, ...,
    integrate 1/SUBSTEPS
    end_step (heavy wears off)

The last integration is collided at the start of the next step, as before,
which is where deaths are handled. Something deadly touched in between marks
the player `doomed`, and they die at the start of the next step.

static/predict.js runs the same scheme for your own ball (it reads SUBSTEPS
from the match's physics).
"""
import itertools
import math

from bonk_game.envs.utils.mechanics import player_collision

SUBSTEPS = 4


def collide_players(players, on_contact=None):
    """Bounce every overlapping pair apart. on_contact(i, j) is told about
    each pair that touched (indexes into `players`)."""
    for (i, a), (j, b) in itertools.combinations(enumerate(players), 2):
        if math.hypot(a.x - b.x, a.y - b.y) < a.r + b.r:
            if on_contact is not None:
                on_contact(i, j)
            player_collision(a, b)


def advance(movers, game_map, substeps=SUBSTEPS, on_contact=None):
    """Move `movers` (the players in play this step) and the map's moving
    parts (game_map.move: the swing, sliders, a sinking floor) through one
    step, in substeps, colliding the players with the level and each other
    in between. (The env calls game_map.step(move=False) first.)
    on_contact(a, b) is told about player pairs that touch (the movers
    themselves)."""
    for p in movers:
        p.begin_step()
    dt = 1.0 / substeps
    for k in range(substeps):
        game_map.move(dt)
        for p in movers:
            p.integrate(dt)
        if k < substeps - 1:
            for p in movers:
                if game_map.collide(p):
                    p.doomed = True
            if len(movers) > 1:
                collide_players(movers, on_contact)
    for p in movers:
        p.end_step()
