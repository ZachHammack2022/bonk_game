"""Maps. Each map owns its level geometry, how players die, and its drawing.

To add a map: subclass Map, then add it to MAPS at the bottom of this file.
It is automatically available in the main menu, the tournament
(`--map <name>`), and as the gym env `bonk_game/bonk-<name>-v0`.
"""
import numpy as np

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.bodies import Block, Swing, collide_block
from bonk_game.envs.utils.mechanics import env_collision, handle_env_collision
from bonk_game.envs.utils.player import player


class Map:
    name = "base"
    title = "Base"
    description = ""

    width = arena.WIDTH
    height = arena.HEIGHT
    # Area used to normalize player positions into [-1, 1]
    obs_bounds = (arena.LEFT, arena.RIGHT, arena.TOP, arena.BOTTOM)
    spawn_box = obs_bounds
    clamp_bottom = True
    max_speed = 20  # player velocity cap (also scales velocity observations)
    # True: "up" is continuous thrust (players can hover). False: "up" jumps,
    # and only when standing on something.
    can_fly = True
    jump_speed = 0
    # Number of map-specific values appended to every agent's observation
    n_extra_obs = 0
    # Points needed to win a match in the playable game
    winning_score = 100
    # In the game, does a death restart the whole round (True) or just
    # respawn the player who died (False)?
    reset_round_on_kill = False

    @property
    def obs_size(self):
        """Length of one agent's observation."""
        return arena.OBS_SIZE + self.n_extra_obs

    def make_players(self):
        left, right, top, bottom = self.obs_bounds
        players = tuple(
            player(arena.RADIUS, left, right, top, bottom, color,
                   spawn=self.spawn_box, clamp_bottom=self.clamp_bottom)
            for color in (arena.P1_COLOR, arena.P2_COLOR)
        )
        for p in players:
            p.v_range = self.max_speed
            p.can_fly = self.can_fly
            p.jump_speed = self.jump_speed
        return players

    def reset(self):
        """Put any moving parts back where they start."""

    def step(self):
        """Advance moving parts by one step (before collisions)."""

    def collide(self, p):
        """Collide a player with the level. Return True if it killed them."""
        raise NotImplementedError

    def extra_obs(self):
        return np.zeros(0)

    def render(self, canvas):
        raise NotImplementedError


class ClassicMap(Map):
    """The original arena: bouncy floor and ceiling, deadly side walls."""

    name = "classic"
    title = "Classic"
    description = "Bouncy floor and ceiling, deadly side walls."

    def __init__(self):
        self.platforms = arena.make_platforms()

    def collide(self, p):
        for obj in self.platforms:
            if env_collision(p, obj):
                if obj.kill:
                    return True
                handle_env_collision(p, obj)
        return False

    def render(self, canvas):
        for obj in self.platforms:
            obj.render(canvas)


class SwingMap(Map):
    """Sinking floor with a pit and a launch pad, and a swing to escape to.

    After a short grace period the whole floor (including the pit and its
    launch pad) starts sinking, and eventually drops off the bottom of the
    screen. The swing hanging in the middle is the only safe spot left, but
    it can be kicked and players can knock each other out of it.

    Players can't fly on this map: "up" is a jump that only works while
    standing on the floor, the launch pad, or the swing seat.

    You die if you fall off the bottom of the screen, leave it to the left
    or right, or get launched way above the top.
    """

    name = "swing"
    title = "Sinking Swing"
    description = "The floor sinks away. Get to the swing, and knock your opponent out."

    FLOOR_Y = 400
    FLOOR_THICKNESS = 16
    FLOOR_LEFT, FLOOR_RIGHT = 110, 570
    HOLE_LEFT, HOLE_RIGHT = 296, 384  # gap in the floor over the pit
    PIT_DEPTH = 56
    WALL = 6  # thickness of the pit walls

    SINK_DELAY = 150  # steps before the floor starts to sink (5s at 30 fps)
    SINK_SPEED = 0.35  # pixels per step
    LAUNCH_SPEED = 25  # enough to fly from the pit up to the swing

    KILL_TOP = -120  # "way too high": well above the top of the screen

    obs_bounds = (0, arena.WIDTH, KILL_TOP, arena.HEIGHT)
    spawn_box = (FLOOR_LEFT + 20, FLOOR_RIGHT - 20, 290, FLOOR_Y - 2)
    clamp_bottom = False
    max_speed = 28  # higher than classic so the launch pad can reach the swing
    # No hovering here, or the sinking floor wouldn't matter: up = jump
    can_fly = False
    jump_speed = 22  # high enough to jump from the floor into the swing
    n_extra_obs = 3  # floor depth, swing angle, swing angular velocity
    winning_score = 5
    reset_round_on_kill = True

    FLOOR_COLOR = (255, 204, 204)
    PIT_COLOR = (200, 160, 160)
    PAD_COLOR = (102, 204, 102)

    def __init__(self):
        self.swing = Swing(pivot_x=arena.WIDTH / 2, pivot_y=24, length=245)
        self.reset()

    def _build_floor(self):
        top, t = self.FLOOR_Y, self.FLOOR_THICKNESS
        pit_bottom = top + self.PIT_DEPTH
        floor = dict(restitution=0.4, friction=0.04)
        return [
            Block(self.FLOOR_LEFT, top, self.HOLE_LEFT, top + t, self.FLOOR_COLOR, **floor),
            Block(self.HOLE_RIGHT, top, self.FLOOR_RIGHT, top + t, self.FLOOR_COLOR, **floor),
            # Pit walls hang down from the edges of the hole
            Block(self.HOLE_LEFT - self.WALL, top + t, self.HOLE_LEFT, pit_bottom,
                  self.PIT_COLOR, **floor),
            Block(self.HOLE_RIGHT, top + t, self.HOLE_RIGHT + self.WALL, pit_bottom,
                  self.PIT_COLOR, **floor),
            # Launch pad at the bottom of the pit
            Block(self.HOLE_LEFT - self.WALL, pit_bottom, self.HOLE_RIGHT + self.WALL,
                  pit_bottom + 10, self.PAD_COLOR, restitution=0.0,
                  launch=self.LAUNCH_SPEED),
        ]

    def reset(self):
        self.steps = 0
        self.sink = 0.0  # how far the floor has dropped
        self.floor = self._build_floor()
        self.swing.reset()

    def step(self):
        self.steps += 1
        speed = self.SINK_SPEED if self.steps > self.SINK_DELAY else 0.0
        self.sink += speed
        for block in self.floor:
            block.vy = speed
            block.move(0, speed)
        self.swing.step()

    def out_of_bounds(self, p):
        return (p.y - p.r > self.height
                or p.x + p.r < 0
                or p.x - p.r > self.width
                or p.y < self.KILL_TOP)

    def collide(self, p):
        p.grounded = False
        for block in self.floor:
            collide_block(p, block)
        self.swing.collide(p)
        return self.out_of_bounds(p)

    def extra_obs(self):
        depth = min(self.sink / (self.height - self.FLOOR_Y + self.PIT_DEPTH), 1.0)
        return np.clip(np.array([
            depth * 2 - 1,
            self.swing.theta / (np.pi / 2),
            self.swing.omega / self.swing.max_omega,
        ]), -1, 1)

    def render(self, canvas):
        import pygame
        # Danger line marks how high is "too high" (only visible if it's on screen)
        if self.KILL_TOP >= 0:
            pygame.draw.line(canvas, (220, 0, 0), (0, self.KILL_TOP), (self.width, self.KILL_TOP), 2)
        self.swing.render(canvas)
        for block in self.floor:
            block.render(canvas)


MAPS = {m.name: m for m in (ClassicMap, SwingMap)}
DEFAULT_MAP = "classic"


def make_map(name=DEFAULT_MAP):
    if name not in MAPS:
        raise ValueError(f"Unknown map {name!r}. Choose from: {', '.join(MAPS)}")
    return MAPS[name]()


def agent_dir(map_name=DEFAULT_MAP):
    """Where trained agents for a map are saved.

    Classic agents stay in ./agents so existing saves keep working.
    """
    return "./agents" if map_name == DEFAULT_MAP else f"./agents/{map_name}"


def env_id(map_name=DEFAULT_MAP):
    return "bonk_game/bonk-v0" if map_name == DEFAULT_MAP else f"bonk_game/bonk-{map_name}-v0"
