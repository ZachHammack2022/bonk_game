"""Keyboard controls for the one human player on this computer.

Each computer has one human player; everyone else in a local match is a
Bot or a trained agent. (Online, every player is on their own computer.)
WASD and the arrow keys both work.
"""
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

from bonk_game.envs.utils.controls import Buttons

MAX_HUMANS = 1

# (up, left, down, right, heavy): any key in a group works. Caps Lock isn't
# used: on macOS it reads as held while toggled.
KEYS = (
    (pygame.K_w, pygame.K_UP),
    (pygame.K_a, pygame.K_LEFT),
    (pygame.K_s, pygame.K_DOWN),
    (pygame.K_d, pygame.K_RIGHT),
    (pygame.K_SPACE, pygame.K_LSHIFT, pygame.K_RSHIFT),
)

# For on-screen hints
MOVE_LABELS = ["W", "A", "S", "D"]
HEAVY_LABELS = ["Space", "Shift"]
HINT = "WASD or arrows  ·  Space to go heavy"


def keyboard_buttons(keys):
    """Buttons held, given pygame.key.get_pressed()."""
    return Buttons(*(any(keys[k] for k in group) for group in KEYS))
