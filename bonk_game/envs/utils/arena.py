"""Shared arena setup, action mapping, and rendering for every bonk env.

The training env and the testing/match env used to each carry their own copy
of this code; keeping it in one place means the physics an agent trains on is
the same physics it is tested and ranked on.
"""
import math
import os

import numpy as np

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

from bonk_game.envs.utils.player import player
from bonk_game.envs.utils.platform import platform

# Screen size
WIDTH = 680
HEIGHT = 480

# Inner bounds of the arena (players spawn between these)
LEFT = 100
RIGHT = 580
TOP = 135
BOTTOM = 420

RADIUS = 20
FORCE = 2  # change in velocity a player gets from one input

P1_COLOR = (255, 107, 107)
P2_COLOR = (77, 171, 247)
P3_COLOR = (177, 132, 255)
P4_COLOR = (255, 202, 58)
PLAYER_COLORS = (P1_COLOR, P2_COLOR, P3_COLOR, P4_COLOR)
MAX_PLAYERS = len(PLAYER_COLORS)
FLOOR_COLOR = (126, 214, 170)
WALL_COLOR = (239, 83, 80)

# Observation length for a single agent: own 6 values + opponent's 6 values
OBS_SIZE = 12

# Map discrete action -> (x direction, y direction, go heavy).
# Actions 0-7 are the eight directions; 8-15 are the same directions while
# going heavy.
_DIRECTIONS = [
    (1, 0), (0, 1), (-1, 0), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
]
ACTIONS = {
    i: np.array([dx, dy, heavy])
    for heavy in (0, 1)
    for i, (dx, dy) in enumerate(_DIRECTIONS, start=8 * heavy)
}
N_ACTIONS = len(ACTIONS)


def make_players():
    p1 = player(RADIUS, LEFT, RIGHT, TOP, BOTTOM, P1_COLOR)
    p2 = player(RADIUS, LEFT, RIGHT, TOP, BOTTOM, P2_COLOR)
    return p1, p2


def make_platforms():
    floor = platform(LEFT, RIGHT, BOTTOM, BOTTOM + 15, FLOOR_COLOR, kill=False)
    left_wall = platform(LEFT - 20, LEFT, TOP - 20, BOTTOM + 15, WALL_COLOR, kill=True)
    right_wall = platform(RIGHT, RIGHT + 20, TOP - 20, BOTTOM + 15, WALL_COLOR, kill=True)
    ceiling = platform(LEFT, RIGHT, TOP - 20, TOP, FLOOR_COLOR, kill=False)
    return [floor, left_wall, right_wall, ceiling]


def apply_action(agent, action):
    """Apply a discrete action (0-15) to a player."""
    dx, dy, heavy = ACTIONS[int(action)]
    agent.move_right(dx * FORCE)
    # Go through move_up so maps where "up" is a jump work for agents too
    if dy < 0:
        agent.move_up(FORCE)
    elif dy > 0:
        agent.move_down(FORCE)
    if heavy:
        agent.make_heavy()


def respawn_apart(to_move, others, max_tries=1000):
    """Reset `to_move` until it doesn't overlap any player in `others`."""
    for _ in range(max_tries):
        to_move.reset()
        if all(math.dist((to_move.x, to_move.y), (o.x, o.y)) > to_move.r + o.r
               for o in others):
            return


def reset_players(players):
    """Reset every player to a random spot with no overlaps."""
    for i, p in enumerate(players):
        respawn_apart(p, players[:i])


class Renderer:
    """Owns the pygame window and draws the arena."""

    def __init__(self, render_mode, fps, caption="Bonk"):
        self.render_mode = render_mode
        self.fps = fps
        self.caption = caption
        self.window = None
        self.clock = None
        self.font = None
        self.quit_requested = False

    def _ensure_init(self):
        if self.font is None:
            pygame.init()
            from bonk_game.ui import theme
            self.font = theme.font(20)
        if self.render_mode == "human" and self.window is None:
            pygame.display.init()
            self.window = pygame.display.set_mode((WIDTH, HEIGHT))
            pygame.display.set_caption(self.caption)
            self.clock = pygame.time.Clock()

    def draw(self, players, game_map, scores=None, timer=None):
        self._ensure_init()
        from bonk_game.ui.painter import Painter
        from bonk_game.ui import theme

        canvas = pygame.Surface((WIDTH, HEIGHT))
        painter = Painter(canvas)
        painter.background()
        game_map.render(painter)
        if timer is not None:
            painter.closing_walls(timer.walls(), WIDTH, HEIGHT, timer.steps / 30)
        for p in players:
            painter.player(p)

        if scores is not None:
            # Scores across the top, in each player's colour
            labels = [self.font.render(str(s), True, c) for s, c in zip(scores, theme.PLAYER_COLORS)]
            if len(labels) == 2:
                canvas.blit(labels[0], (20, 12))
                canvas.blit(labels[1], (WIDTH - 20 - labels[1].get_width(), 12))
            else:
                for i, label in enumerate(labels):
                    canvas.blit(label, (20 + i * 50, 12))

        if self.render_mode == "human":
            self.window.blit(canvas, canvas.get_rect())
            # Let the user close the window instead of having to kill the process
            for event in pygame.event.get(pygame.QUIT):
                self.quit_requested = True
            pygame.event.pump()
            pygame.display.update()
            self.clock.tick(self.fps)
            return None
        return np.transpose(np.array(pygame.surfarray.pixels3d(canvas)), axes=(1, 0, 2))

    def close(self):
        if self.window is not None:
            pygame.display.quit()
            pygame.quit()
            self.window = None
            self.font = None
