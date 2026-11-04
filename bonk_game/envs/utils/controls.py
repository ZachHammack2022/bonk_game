"""Player inputs, independent of where they come from.

Each step the game takes one input per player: either a discrete action
(0-15, what trained agents and the Bot output; see arena.ACTIONS) or the
set of buttons that player is holding. The local game turns keyboard
state into Buttons (bonk_game/ui/keys.py); a game server would build them
from each client's messages instead.
"""
from collections import namedtuple

from bonk_game.envs.utils import arena

Buttons = namedtuple("Buttons", "up left down right heavy", defaults=(False,) * 5)
NO_BUTTONS = Buttons()


def apply_input(p, inp):
    """Apply one step of input to player `p`. None means no input."""
    if inp is None:
        return
    if isinstance(inp, Buttons):
        if inp.up:
            p.move_up(arena.FORCE)
        if inp.left:
            p.move_left(p.push)
        if inp.down:
            p.move_down(p.push)
        if inp.right:
            p.move_right(p.push)
        if inp.heavy:
            p.make_heavy()
    else:
        arena.apply_action(p, inp)
