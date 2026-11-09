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
    """A ring whose two halves slide out, as a bonk.io map has it.

    You stand on a long bar (the top rope). Under it, between it and a
    second bar, each half of the ring has an arm reaching to the middle,
    with a corner block and a leaning post on its outer end. The halves are
    feather-light: run into a post, or ride a corner, and you shove that
    half out sideways, taking you with it over the edge if you keep going.
    Let go and it's pulled back home, where it stops against the middle.

    Measured from a recording of the map in bonk.io (November 2026), with
    its settings for a half: free moving, density 0.01, no bounce, a springy
    joint (spring force 500). Out of the way, a half comes back with about
    500 px/s^2 (plus a little more the further out it is) and is home in
    about 0.75 s. Sizes are the recording's, with balls the size of ours.
    """

    name = "slider"
    title = "Sliding Platform"
    description = "Each half of the ring slides out when you shove its post. Ride it out, or push someone off with it."

    CENTER = 340
    TOP = 300              # top of the bar you stand on
    BAR_THICKNESS = 12     # the two bars (ropes)
    HALF_WIDTH = 254       # the bars reach this far either side of the middle
    ARM_TOP, ARM_BOTTOM = 314, 334    # each half's arm, between the bars
    BOTTOM_BAR = 338       # top of the lower bar
    CORNER_WIDTH = 78      # corner blocks, the full height of the ring
    POST_WIDTH, POST_HEIGHT = 12, 113
    POST_LEAN = 7.4        # degrees the posts lean outward
    POST_IN = 10           # the post's foot, in from the corner's outer edge
    TRAVEL = 400           # how far a half can slide out
    HALF_MASS = 0.06       # a ball is 1 (bonk's density 0.01)
    # Pulled home: 500 px/s^2, plus 2.5 per second^2 for each px out, at the
    # default speed (22.5 steps a second); in px per step per step
    HOME_PULL = 500 / 22.5 ** 2
    HOME_SPRING = 2.5 / 22.5 ** 2

    spawn_box = (CENTER - HALF_WIDTH + 14, CENTER + HALF_WIDTH - 14, 200, TOP - 2)
    players = (2, 6)
    n_extra_obs = 4  # each half: how far out, and how fast

    def __init__(self):
        super().__init__()

    def _half(self, side):
        """The left (-1) or right (+1) half: arm, corner block and post."""
        c, hw = self.CENTER, self.HALF_WIDTH
        inner = c + side * 2.5                    # (a hair from the other arm)
        edge = c + side * (hw + 2)                # the corner's inner edge
        outer = edge + side * self.CORNER_WIDTH  # and its outer one
        bottom = self.BOTTOM_BAR + self.BAR_THICKNESS
        half = dict(restitution=0.0, friction=0.04)  # (bonk: no bounce; its friction's off for players)
        x1, x2 = sorted((inner, edge))
        # (The halves are all one colour, apart from the bars you stand on,
        # so you can see what moves)
        arm = Block(x1, self.ARM_TOP, x2, self.ARM_BOTTOM, self.POST_COLOR, **half)
        x1, x2 = sorted((edge, outer))
        corner = Block(x1, self.TOP, x2, bottom, self.POST_COLOR, **half)
        # The post's foot sits a little into the corner so there's no gap
        post = OrientedBlock.standing(outer - side * self.POST_IN, self.TOP + 3, self.POST_WIDTH,
                                      self.POST_HEIGHT + 3, side * self.POST_LEAN, self.POST_COLOR, **half)
        travel = (-self.TRAVEL, 0) if side < 0 else (0, self.TRAVEL)
        return SlidingPlatform([arm, corner, post], mass=self.HALF_MASS, travel=travel, damping=1.0,
                               max_speed=24, end_bounce=0.3, home_pull=self.HOME_PULL,
                               home_spring=self.HOME_SPRING, home_bounce=0.0)

    def reset(self):
        super().reset()
        c, hw, top, t = self.CENTER, self.HALF_WIDTH, self.TOP, self.BAR_THICKNESS
        bar = dict(restitution=0.3, friction=0.04)
        self.blocks = [
            Block(c - hw, top, c + hw, top + t, self.PLATFORM_COLOR, **bar),
            Block(c - hw, self.BOTTOM_BAR, c + hw, self.BOTTOM_BAR + t, self.PLATFORM_COLOR, **bar),
        ]
        self.halves = [self._half(-1), self._half(1)]
        self.bodies = list(self.halves)

    @property
    def platform(self):
        """(The right half: what used to be the one sliding platform)"""
        return self.halves[1]

    def safe_x_range(self):
        return self.CENTER - self.HALF_WIDTH, self.CENTER + self.HALF_WIDTH

    def extra_obs(self):
        values = []
        for h in self.halves:
            values += [h.offset / h.travel, h.vx / h.max_speed]
        return np.clip(np.array(values), -1, 1)


class SwingMap(OpenMap):
    """A flat, bouncy floor that sinks, and a swing to escape to (as bonk.io's
    version of the map has it).

    After a short grace period the whole floor starts sinking, and eventually drops off the bottom of the
    screen. The swing hanging in the middle is the only safe spot left, but
    it can be kicked and players can knock each other out of it.
    """

    name = "swing"
    title = "Sinking Swing"
    description = "The floor sinks away. Get to the swing, and knock your opponent out."

    FLOOR_Y = 400
    FLOOR_THICKNESS = 16
    FLOOR_LEFT, FLOOR_RIGHT = 110, 570

    SINK_DELAY = 150  # steps before the floor starts to sink (5s at 30 fps)
    # Pixels per step: 7 px a second at the default speed, as bonk.io's
    # "Falling floor" sinks (measured from a recording). There it's a free
    # body with density 999 and linear drag 20: nothing a player does moves
    # it, and it falls at a steady speed, never tilting (spin drag 999). A
    # floor driven at that speed is the same thing, and the browser predicts
    # it exactly.
    SINK_SPEED = 0.31
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

    def __init__(self):
        # Hung as in bonk.io: from 500 px up, far above the top of the screen
        self.swing = Swing(pivot_x=arena.WIDTH / 2, pivot_y=self.SEAT_Y - self.ROPE, length=self.ROPE)
        super().__init__()

    def _build_floor(self):
        top, t = self.FLOOR_Y, self.FLOOR_THICKNESS
        # bonk's "Falling floor": bounciness 0.8. You bounce on it, and pump
        # each bounce higher: down as you fall, up as you land. (Its friction,
        # 0.5, is off for players there, "Fric Players: No": balls slide)
        floor = dict(restitution=0.8, friction=0.04)
        # One flat piece, all the way across (it used to have a pit in the
        # middle with a launch pad: a jump reaches the swing without one)
        return [Block(self.FLOOR_LEFT, top, self.FLOOR_RIGHT, top + t, self.FLOOR_COLOR, **floor)]

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
        # The floor moves at a speed set each step
        self.sinking = MovingBlocks(self.blocks)
        self.swing.reset()
        self.bodies = [self.swing]

    def pieces(self):
        return [], [self.swing, self.sinking]

    def step(self, move=True):
        self.sinking.vy = self.SINK_SPEED if self.steps >= self.SINK_DELAY else 0.0
        super().step(move)

    def extra_obs(self):
        depth = min(self.sink / (self.height - self.FLOOR_Y), 1.0)
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
