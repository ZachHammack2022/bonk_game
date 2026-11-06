"""Moving everything through one physics step.

A step is 1/30 s at normal speed (what agents, the network and replays
count in). The map's Box2D world (world.py) does the moving, in SUBSTEPS
Box2D steps, so nothing moves more than a few pixels between collision
checks and contacts settle within the step they happen.

A step, for the players still in play:

    deaths (by the env: anyone who touched something deadly, or left the
            play area, during the last step)
    begin_step (jumping, which needs to know who's standing on something)
    Box2D step, bonk's rules, Box2D step, rules, ... (SUBSTEPS times)
    end_step (heavy lets go unless held)

static/physics.js runs the same scheme in the browser (it's sent SUBSTEPS
with the rest of the physics).
"""
from bonk_game.envs.utils.world import SUBSTEPS

# How fast the world runs: the share of a "physics step" that passes in each
# 1/30 s tick. Below 1 everything happens in slow motion: moves, falls, pushes
# and heavy wearing off all take longer, but every path is the same (jumps go
# as high, bounces as far), so the maps play the same, just with more time to
# think. 1.0 is the original speed, which felt too quick to plan anything.
# Rooms can pick another (lobby.SPEEDS).
TIME_SCALE = 0.75

__all__ = ["SUBSTEPS", "TIME_SCALE", "advance"]


def advance(movers, game_map, substeps=SUBSTEPS, on_contact=None, time_scale=1.0):
    """Move `movers` (the players in play this step) and the map's moving
    parts through one step. Players not in `movers` sit out (they're taken
    out of the world). on_contact(a, b) is told about pairs of movers that
    touch (indexes into movers). time_scale: how much of a physics step
    passes (TIME_SCALE)."""
    game_map.world.step(movers, time_scale=time_scale, substeps=substeps, on_contact=on_contact)
