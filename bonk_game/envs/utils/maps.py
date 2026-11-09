"""Maps. Each map owns its level geometry, how players die, and its drawing.

To add a map: write a JSON file (see bonk_game/envs/utils/map_files.py and
bonk_game/maps/), or subclass Map and add it to MAPS at the bottom of this
file.
It is automatically available in the main menu, in `main.py --train`, and as the gym env `bonk_game/bonk-<name>-v0`.
"""
import numpy as np

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.bodies import Block, MovingBlocks, OrientedBlock, SlidingPlatform, Swing
from bonk_game.envs.utils.player import new_rng, player
from bonk_game.envs.utils.world import LIFT, World
from bonk_game.ui import theme


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
    # Sideways and down push from an input ("up" on fly maps is arena.FORCE)
    push_force = arena.FORCE
    # Jump maps: the share of gravity holding "up" in the air cancels
    hover = 0.0
    # Number of map-specific values appended to every agent's observation
    n_extra_obs = 0
    # Points needed to win a match in the playable game
    winning_score = 100
    # In the game, does a death restart the whole round (True) or just
    # respawn the player who died (False)?
    reset_round_on_kill = False
    # Seconds per round in the game before sudden death (closing walls)
    # starts; 0 turns it off. See bonk_game/envs/utils/timer.py.
    round_time = 45
    # (left, right) x where the sudden-death walls appear
    sudden_death_start = (0, arena.WIDTH)
    # Can players respawn mid-round (the web version's respawn modes)? Not on
    # maps that change for good during a round, like a floor that sinks away.
    respawn_ok = True
    # How many players the map is made for (the web lobby holds to it)
    players = (arena.MIN_PLAYERS, arena.MAX_PLAYERS)

    @property
    def obs_size(self):
        """Length of one agent's observation."""
        return arena.OBS_SIZE + self.n_extra_obs

    def make_players(self, n=2, colors=None, rng=None):
        """`n` players (2-10), each in its own colour. `colors`: an index into
        theme.PLAYER_COLORS per player (default: the first n, in order).
        rng: random numbers for where they spawn, shared by all of them
        (player.new_rng() if not given)."""
        if not arena.MIN_PLAYERS <= n <= arena.MAX_PLAYERS:
            raise ValueError(f"{n} players: need {arena.MIN_PLAYERS}-{arena.MAX_PLAYERS}")
        colors = list(range(n)) if colors is None else list(colors)
        if len(colors) != n or len(set(colors)) != n:
            raise ValueError("need a different colour for each player")
        left, right, top, bottom = self.obs_bounds
        rng = new_rng() if rng is None else rng
        players = tuple(
            player(arena.RADIUS, left, right, top, bottom, theme.PLAYER_COLORS[c],
                   spawn=self.spawn_box, clamp_bottom=self.clamp_bottom, rng=rng)
            for c in colors
        )
        for p in players:
            p.v_range = self.max_speed
            p.can_fly = self.can_fly
            p.jump_speed = self.jump_speed * LIFT  # (world.LIFT: same heights)
            p.push = self.push_force
            p.hover = self.hover
        return players

    def place_players(self, players):
        """Reset every player at the start of a round, spread over the spawn box."""
        points = arena.spawn_points(len(players), self.spawn_box, arena.RADIUS, players[0].rng)
        for p, (x, y) in zip(players, points):
            p.reset()
            p.x, p.y = x, y

    _world = None

    def reset(self):
        """Put any moving parts back where they start."""
        self._world = None

    def pieces(self):
        """(static pieces, moving parts) that make up the level's physics."""
        raise NotImplementedError

    @property
    def world(self):
        """The level's Box2D world (world.py), made afresh after a reset."""
        if self._world is None:
            self._world = World(*self.pieces())
        return self._world

    def step(self, move=True):
        """A new step. move: also move the moving parts the whole step now,
        with no players (for tools and tests). The envs pass False and move
        everything together (stepping.advance)."""
        if move:
            self.move(1.0)

    def move(self, dt):
        """Move the moving parts (and nobody else) for `dt` of a step."""
        self.world.step((), time_scale=dt)

    def killed(self, p):
        """Has the level knocked this player out? True if they touched
        something deadly during the last step (`doomed`) or are touching one
        now (put there by hand), or (on open maps) left the play area."""
        return bool(p.doomed) or self.world.deadly(p)

    def extra_obs(self):
        return np.zeros(0)

    # How far the built-in bot keeps from the ends of safe_x_range()
    bot_margin = 20

    def safe_x_range(self):
        """Left/right x of the main ground right now (used by the built-in bot)."""
        return self.spawn_box[0], self.spawn_box[1]

    def render(self, painter):
        """Draw the level with a bonk_game.ui.painter.Painter."""
        raise NotImplementedError


class ClassicMap(Map):
    """The original arena: bouncy floor and ceiling, deadly side walls."""

    name = "classic"
    title = "Classic"
    description = "Bouncy floor and ceiling, deadly side walls."
    bot_margin = 60  # the walls kill on touch, so keep well clear
    round_time = 30  # players respawn here, so this is time between points
    players = (2, 8)
    sudden_death_start = (arena.LEFT, arena.RIGHT)

    def __init__(self):
        self.platforms = arena.make_platforms()

    def pieces(self):
        return self.platforms, []

    def render(self, painter):
        for obj in self.platforms:
            if obj.kill:
                painter.block(obj.x1, obj.y1, obj.x2, obj.y2, theme.HAZARD, "hazard")
            else:
                painter.block(obj.x1, obj.y1, obj.x2, obj.y2, theme.PLATFORM)


class OpenMap(Map):
    """Base for bonk-style maps floating in open space.

    No walls: you die if you fall off the bottom of the screen, leave it to
    the left or right, or get launched way above the top. Players can't fly:
    "up" is a jump that only works while standing on something. Each death
    gives the other player a point and restarts the round.

    Subclasses fill in `self.blocks` (static Blocks) and/or `self.bodies`
    (moving parts from bodies.py, like a Swing or SlidingPlatform); the
    map's Box2D world (world.py) is made from them after each reset.
    """

    KILL_TOP = -120  # "way too high": well above the top of the screen

    obs_bounds = (0, arena.WIDTH, KILL_TOP, arena.HEIGHT)
    clamp_bottom = False
    max_speed = 28
    can_fly = False
    # Movement measured from bonk.io (see arena.OPEN_PUSH): a jump leaves the
    # ground at ~7 px a tick (at the default speed) and peaks ~32 px up if you
    # let go of "up", ~120 px if you hold it and hover.
    jump_speed = 10.0
    push_force = arena.OPEN_PUSH
    hover = arena.OPEN_HOVER
    winning_score = 5
    reset_round_on_kill = True

    PLATFORM_COLOR = theme.PLATFORM
    POST_COLOR = theme.POST

    def __init__(self):
        self.blocks = []
        self.bodies = []
        self.reset()

    def reset(self):
        super().reset()
        self.steps = 0

    def pieces(self):
        return self.blocks, self.bodies

    def step(self, move=True):
        self.steps += 1
        super().step(move)

    def out_of_bounds(self, p):
        return (p.y - p.r > self.height
                or p.x + p.r < 0
                or p.x - p.r > self.width
                or p.y < self.KILL_TOP)

    def killed(self, p):
        return super().killed(p) or self.out_of_bounds(p)

    def render(self, painter):
        painter.danger_edges()
        for body in self.bodies:
            body.render(painter)
        for block in self.blocks:
            block.render(painter)


class PlatformMap(OpenMap):
    """One floating platform. Knock your opponent off it."""

    name = "platform"
    title = "Floating Platform"
    description = "A single platform in open space. Last one on it wins."

    LEFT, RIGHT = 200, 480
    TOP = 300
    THICKNESS = 16

    spawn_box = (LEFT, RIGHT, 200, TOP - 2)
    players = (2, 6)

    def __init__(self):
        super().__init__()
        self.blocks = [Block(self.LEFT, self.TOP, self.RIGHT, self.TOP + self.THICKNESS,
                             self.PLATFORM_COLOR, restitution=0.3, friction=0.04)]


class SliderMap(OpenMap):
    """A heavy platform on a rail that players push around.

    Every hit and every roll shoves the platform the other way, so players
    can rock it back and forth to build momentum and fling each other off.
    Outward-leaning posts at both ends act as bumpers you can bounce off.
    """

    name = "slider"
    title = "Sliding Platform"
    description = "Hits push the platform. Rock it to build momentum and fling your opponent."

    LEFT, RIGHT = 200, 480
    TOP = 300
    THICKNESS = 16
    POST_WIDTH, POST_HEIGHT = 10, 46
    POST_LEAN = 18  # degrees the posts lean outward
    TRAVEL = 140  # how far it can slide either way

    spawn_box = (LEFT + 10, RIGHT - 10, 200, TOP - 2)
    players = (2, 6)
    n_extra_obs = 2  # platform offset and velocity


    def __init__(self):
        super().__init__()

    def reset(self):
        super().reset()
        surface = dict(restitution=0.3, friction=0.08)
        post = dict(restitution=0.6, friction=0.0)
        top, pw, ph = self.TOP, self.POST_WIDTH, self.POST_HEIGHT
        self.platform = SlidingPlatform([
            Block(self.LEFT, top, self.RIGHT, top + self.THICKNESS, self.PLATFORM_COLOR, **surface),
            # Posts lean outward, so they catch you like the lip of a bowl.
            # Their feet sit a little into the platform so there's no gap.
            OrientedBlock.standing(self.LEFT + pw / 2, top + 3, pw, ph + 3, -self.POST_LEAN,
                                   self.POST_COLOR, **post),
            OrientedBlock.standing(self.RIGHT - pw / 2, top + 3, pw, ph + 3, self.POST_LEAN,
                                   self.POST_COLOR, **post),
        ], mass=6.0, travel=self.TRAVEL)
        self.bodies = [self.platform]

    def safe_x_range(self):
        return self.LEFT + self.platform.offset, self.RIGHT + self.platform.offset

    def extra_obs(self):
        return np.clip(np.array([
            self.platform.offset / self.TRAVEL,
            self.platform.vx / self.platform.max_speed,
        ]), -1, 1)

    def render(self, painter):
        # The rail the platform slides along
        painter.rail(self.LEFT - self.TRAVEL, self.RIGHT + self.TRAVEL,
                     self.TOP + self.THICKNESS + 10)
        super().render(painter)


class SwingMap(OpenMap):
    """Sinking floor with a pit and a launch pad, and a swing to escape to.

    After a short grace period the whole floor (including the pit and its
    launch pad) starts sinking, and eventually drops off the bottom of the
    screen. The swing hanging in the middle is the only safe spot left, but
    it can be kicked and players can knock each other out of it.
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
    # Pixels per step: 7 px a second at the default speed, as bonk.io's
    # "Falling floor" sinks (measured from a recording). There it's a free
    # body with density 999 and linear drag 20: nothing a player does moves
    # it, and it falls at a steady speed, never tilting (spin drag 999). A
    # floor driven at that speed is the same thing, and the browser predicts
    # it exactly.
    SINK_SPEED = 0.31
    LAUNCH_SPEED = 25  # enough to fly from the pit up to the swing
    SEAT_Y = 280  # the middle of the swing's seat, hanging still
    ROPE = 500
    # The map is built around jumping up into the swing, so it keeps the
    # original big jump (~174 px) instead of the bonk.io hop and hover
    jump_speed = 23.5
    hover = 0.0

    spawn_box = (FLOOR_LEFT + 20, FLOOR_RIGHT - 20, 290, FLOOR_Y - 2)
    respawn_ok = False  # the floor is gone by the end of a round
    players = (2, 6)
    n_extra_obs = 3  # floor depth, swing angle, swing angular velocity

    FLOOR_COLOR = theme.PLATFORM
    PIT_COLOR = theme.PIT
    PAD_COLOR = theme.PAD

    def __init__(self):
        # Hung as in bonk.io: from 500 px up, far above the top of the screen
        self.swing = Swing(pivot_x=arena.WIDTH / 2, pivot_y=self.SEAT_Y - self.ROPE, length=self.ROPE)
        super().__init__()

    def _build_floor(self):
        top, t = self.FLOOR_Y, self.FLOOR_THICKNESS
        pit_bottom = top + self.PIT_DEPTH
        # bonk's "Falling floor": bounciness 0.8. You bounce on it, and pump
        # each bounce higher: down as you fall, up as you land. (Its friction,
        # 0.5, is off for players there, "Fric Players: No": balls slide)
        floor = dict(restitution=0.8, friction=0.04)
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

    @property
    def floor(self):
        return self.blocks

    @property
    def sink(self):
        """How far the floor has dropped."""
        return self.sinking.oy

    def reset(self):
        super().reset()
        self.blocks = self._build_floor()
        # The floor (pit and pad included) moves as one, at a speed set each step
        self.sinking = MovingBlocks(self.blocks)
        self.swing.reset()
        self.bodies = [self.swing]

    def pieces(self):
        return [], [self.swing, self.sinking]

    def step(self, move=True):
        self.sinking.vy = self.SINK_SPEED if self.steps >= self.SINK_DELAY else 0.0
        super().step(move)

    def extra_obs(self):
        depth = min(self.sink / (self.height - self.FLOOR_Y + self.PIT_DEPTH), 1.0)
        return np.clip(np.array([
            depth * 2 - 1,
            self.swing.theta / (np.pi / 2),
            self.swing.omega / self.swing.max_omega,
        ]), -1, 1)


MAPS = {m.name: m for m in (ClassicMap, PlatformMap, SliderMap, SwingMap)}
DEFAULT_MAP = "classic"

# Maps from JSON files (bonk_game/maps/, ./maps/, $BONK_MAPS); see map_files.py
from bonk_game.envs.utils.map_files import load_all as _load_map_files  # noqa: E402

MAPS.update(_load_map_files(MAPS))


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
