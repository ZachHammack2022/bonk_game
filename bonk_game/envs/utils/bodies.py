"""The pieces maps are made of, and their moving parts.

Pieces (Block, OrientedBlock, Bumper) say where something solid is and how
it behaves: bounce, friction, launch, kill. Moving parts group pieces on one
Box2D body that moves: a SlidingPlatform on a rail, a Swing on a rope, and
MovingBlocks (driven at a set speed, like a sinking floor).

Box2D (world.py) does the colliding and moving. Each moving part keeps its
own state (a slider's offset and speed, a swing's angle...) for the rest of
the game, and writes it into its body before a step (push) and reads it
back after each substep (after_substep).
"""
import math


from bonk_game.envs.utils.world import (
    PPM, STEP_SECONDS, add_piece, piece_spec, set_mass, speed_from_b2, speed_to_b2, to_m,
)


def damping_per_second(per_step):
    """Box2D linear damping that keeps `per_step` of a body's speed each step."""
    return -math.log(per_step) / STEP_SECONDS


class Block:
    """A rectangle players collide with.

    Args:
        restitution: how much of the impact speed is bounced back (0-1)
        friction: how much grip the surface has (0-1; see world.py)
        launch: if set, anything landing on top is fired upward at this speed
        kill: touching the block kills the player
    """

    def __init__(self, x1, y1, x2, y2, color, restitution=0.5, friction=0.0,
                 launch=None, kill=False):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.color = color
        self.restitution = restitution
        self.friction = friction
        self.launch = launch
        self.kill = kill
        self.vx = 0.0
        self.vy = 0.0

    def move(self, dx, dy):
        self.x1 += dx
        self.x2 += dx
        self.y1 += dy
        self.y2 += dy

    def rect(self):
        return self.x1, self.y1, self.x2, self.y2

    # Normal of the face a launch pad fires from (its top)
    up = (0.0, -1.0)
    # Attributes that change as it moves (blended when drawing)
    motion_attrs = ("x1", "y1", "x2", "y2")

    def render(self, painter):
        painter.draw_block(self)


class OrientedBlock(Block):
    """A rectangle rotated by `angle` degrees (clockwise on screen) about
    its centre: slopes, ramps and leaning posts. Same options as Block."""

    motion_attrs = ("cx", "cy")

    def __init__(self, cx, cy, w, h, angle, color, **kwargs):
        super().__init__(0, 0, 0, 0, color, **kwargs)
        self.cx, self.cy, self.w, self.h = cx, cy, w, h
        self.angle = angle
        a = math.radians(angle)
        self.cos, self.sin = math.cos(a), math.sin(a)
        self.up = (self.sin, -self.cos)  # its top face's normal

    @classmethod
    def standing(cls, x, y, w, h, lean, color, **kwargs):
        """A post whose bottom centre is at (x, y), leaning `lean` degrees
        (positive leans right)."""
        a = math.radians(lean)
        return cls(x + h / 2 * math.sin(a), y - h / 2 * math.cos(a), w, h, lean, color, **kwargs)

    def move(self, dx, dy):
        self.cx += dx
        self.cy += dy

    def to_world(self, x, y):
        return x * self.cos - y * self.sin, x * self.sin + y * self.cos

    def corners(self):
        hw, hh = self.w / 2, self.h / 2
        return [(self.cx + wx, self.cy + wy) for wx, wy in
                (self.to_world(x, y) for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)))]

    def rect(self):
        """Axis-aligned bounding box."""
        xs, ys = zip(*self.corners())
        return min(xs), min(ys), max(xs), max(ys)


class Bumper(Block):
    """A round piece. With `launch` set it's a pinball bumper: anything
    touching it is fired straight away from its centre at that speed."""

    motion_attrs = ("cx", "cy")

    def __init__(self, cx, cy, radius, color, **kwargs):
        super().__init__(0, 0, 0, 0, color, **kwargs)
        self.cx, self.cy, self.radius = cx, cy, radius
        self.up = None  # launches from every side

    def move(self, dx, dy):
        self.cx += dx
        self.cy += dy

    def rect(self):
        r = self.radius
        return self.cx - r, self.cy - r, self.cx + r, self.cy + r


class _Part:
    """A moving part: pieces on one Box2D body. Subclasses say how the body
    is made and how its state maps to the body."""

    kind = "part"

    def x_y(self):
        """Where the body is (px)."""
        raise NotImplementedError

    def velocity(self):
        """How fast the body moves (px per step)."""
        raise NotImplementedError

    def state(self):
        x, y = self.x_y()
        vx, vy = self.velocity()
        return [round(x, 2), round(y, 2), round(vx, 3), round(vy, 3)]

    def push(self):
        """Write our state into the body (if it changed since we read it)."""
        x, y = self.x_y()
        if self._at != (x, y):
            self.body.transform = ((to_m(x), to_m(y)), 0)
        vx, vy = self.velocity()
        self.body.linearVelocity = (speed_to_b2(vx), speed_to_b2(vy))

    def before_substep(self):
        return None

    def _read(self):
        """The body's (x, y, vx, vy), in px and px per step."""
        pos, vel = self.body.position, self.body.linearVelocity
        return pos.x * PPM, pos.y * PPM, speed_from_b2(vel.x), speed_from_b2(vel.y)

    def _set_velocity(self, vx, vy):
        self.body.linearVelocity = (speed_to_b2(vx), speed_to_b2(vy))


class SlidingPlatform(_Part):
    """A group of blocks that slides left/right as one heavy body.

    It only moves horizontally (on a rail: a Box2D prismatic joint): players
    hitting it or rolling on it push it, and it pushes them back. It slowly
    comes to a stop and bounces softly off the ends of its rail.

    Args:
        blocks: the Blocks that make up the platform, at their start positions
        mass: compared to a player's mass of 1 (5 when heavy)
        travel: how far it may slide either way from where it starts
        damping: share of its speed kept each step
    """

    kind = "slider"

    def __init__(self, blocks, mass=6.0, travel=150, damping=0.992,
                 max_speed=12, end_bounce=0.5):
        self.blocks = blocks
        self.mass = mass
        self.travel = travel
        self.damping = damping
        self.max_speed = max_speed
        self.end_bounce = end_bounce
        self.offset = 0.0  # how far it has slid from the start (right is +)
        self.vx = 0.0

    def x_y(self):
        return self.offset, 0.0

    def velocity(self):
        return self.vx, 0.0

    def attach(self, world, ground):
        self.body = world.CreateDynamicBody(position=(to_m(self.offset), 0), fixedRotation=True,
                                            gravityScale=0,
                                            linearDamping=damping_per_second(self.damping))
        for block in self.blocks:
            add_piece(self.body, block, (self.offset, 0.0))
        set_mass(self.body, self.mass)
        world.CreatePrismaticJoint(bodyA=ground, bodyB=self.body, anchor=self.body.position, axis=(1, 0),
                                   lowerTranslation=to_m(-self.travel - self.offset),
                                   upperTranslation=to_m(self.travel - self.offset), enableLimit=True)
        self._origin = [(b, piece_spec(b, (self.offset, 0.0))) for b in self.blocks]
        self._at = self._attached = (self.offset, 0.0)

    def describe(self):
        return {"kind": self.kind, "at": list(self._attached), "mass": self.mass, "travel": self.travel,
                "damping": self.damping, "max_speed": self.max_speed, "end_bounce": self.end_bounce,
                "pieces": [spec for _, spec in self._origin]}

    def before_substep(self):
        return self.vx

    def after_substep(self, vx_before):
        x, _, vx, _ = self._read()
        if abs(x) >= self.travel - 0.05 and vx_before * x > 0:
            # Hit the end of the rail: bounce back a little
            vx = -vx_before * self.end_bounce
        vx = max(-self.max_speed, min(self.max_speed, vx))
        self._set_velocity(vx, 0.0)
        dx = x - self.offset
        self.offset, self.vx = x, vx
        self._at = (x, 0.0)
        for block in self.blocks:
            block.move(dx, 0)
            block.vx = vx

    def render(self, painter):
        # Angled pieces first, so flat ones cover their feet
        for block in sorted(self.blocks, key=lambda b: not hasattr(b, "angle")):
            painter.draw_block(block)


class Swing(_Part):
    """A pendulum with a cup-shaped seat hanging from a fixed pivot.

    The seat stays level (like a real swing seat) while the rope (a Box2D
    distance joint) swings. Players bump it to set it moving, heavier
    players kick harder, and a player sitting in the cup gets carried along
    with it.
    """

    kind = "swing"

    def __init__(self, pivot_x, pivot_y, length, seat_width=96, lip_height=18,
                 thickness=8, mass=4.0, damping=0.997, max_omega=0.12,
                 restitution=0.15, friction=0.35):
        self.px, self.py = pivot_x, pivot_y
        self.length = length
        self.seat_width = seat_width
        self.lip_height = lip_height
        self.thickness = thickness
        self.mass = mass
        self.damping = damping
        self.max_omega = max_omega
        self.restitution = restitution
        self.friction = friction
        self.reset()

    def reset(self):
        self.theta = 0.0  # angle of the rope from straight down (radians)
        self.omega = 0.0  # angular velocity (radians per step)

    # --- kinematics ---------------------------------------------------
    def seat_pos(self):
        """Centre of the top of the seat."""
        return (self.px + self.length * math.sin(self.theta),
                self.py + self.length * math.cos(self.theta))

    def tangent(self):
        """Unit direction the seat moves in for positive omega."""
        return math.cos(self.theta), -math.sin(self.theta)

    def velocity(self):
        tx, ty = self.tangent()
        speed = self.length * self.omega
        return speed * tx, speed * ty

    def x_y(self):
        return self.seat_pos()

    # --- shape --------------------------------------------------------
    def rects(self):
        """Seat base and the two lips that make it a cup, as (x1, y1, x2, y2)."""
        sx, sy = self.seat_pos()
        half, t, lip = self.seat_width / 2, self.thickness, self.lip_height
        base = (sx - half, sy, sx + half, sy + t)
        left_lip = (sx - half, sy - lip, sx - half + t, sy)
        right_lip = (sx + half - t, sy - lip, sx + half, sy)
        return [base, left_lip, right_lip]

    def attach(self, world, ground):
        sx, sy = self.seat_pos()
        self.body = world.CreateDynamicBody(position=(to_m(sx), to_m(sy)), fixedRotation=True,
                                            linearDamping=damping_per_second(self.damping))
        seat = [Block(*r, None, restitution=self.restitution, friction=self.friction) for r in self.rects()]
        for piece in seat:
            add_piece(self.body, piece, (sx, sy))
        self._pieces = [piece_spec(piece, (sx, sy)) for piece in seat]
        set_mass(self.body, self.mass)
        world.CreateDistanceJoint(bodyA=ground, bodyB=self.body, anchorA=(to_m(self.px), to_m(self.py)),
                                  anchorB=self.body.position, frequencyHz=0, dampingRatio=0)
        self._at = self._attached = (sx, sy)

    def describe(self):
        return {"kind": self.kind, "at": [round(v, 3) for v in self._attached],
                "pivot": [self.px, self.py], "length": self.length,
                "mass": self.mass, "damping": self.damping, "max_omega": self.max_omega,
                "pieces": self._pieces}

    def after_substep(self, _):
        x, y, vx, vy = self._read()
        self.theta = math.atan2(x - self.px, y - self.py)
        tx, ty = self.tangent()
        omega = (vx * tx + vy * ty) / self.length
        if abs(omega) > self.max_omega:
            omega = math.copysign(self.max_omega, omega)
            self._set_velocity(*(v * omega * self.length for v in (tx, ty)))
        self.omega = omega
        self._at = self.seat_pos()

    def render(self, painter):
        painter.swing(self)


class MovingBlocks(_Part):
    """Blocks that move together at a speed the map sets (vx, vy, px per
    step), like a sinking floor. Nothing pushes them (a Box2D kinematic
    body); they carry what's on them."""

    kind = "mover"

    def __init__(self, blocks):
        self.blocks = blocks
        self.ox = self.oy = 0.0  # how far they've moved
        self.vx = self.vy = 0.0

    def x_y(self):
        return self.ox, self.oy

    def velocity(self):
        return self.vx, self.vy

    def attach(self, world, ground):
        self.body = world.CreateKinematicBody(position=(to_m(self.ox), to_m(self.oy)))
        for block in self.blocks:
            add_piece(self.body, block, (self.ox, self.oy))
        self._origin = [piece_spec(b, (self.ox, self.oy)) for b in self.blocks]
        self._at = self._attached = (self.ox, self.oy)

    def describe(self):
        return {"kind": self.kind, "at": list(self._attached), "pieces": self._origin}

    def after_substep(self, _):
        x, y, _, _ = self._read()
        dx, dy = x - self.ox, y - self.oy
        self.ox, self.oy = x, y
        self._at = (x, y)
        for block in self.blocks:
            block.move(dx, dy)
            block.vx, block.vy = self.vx, self.vy

    def render(self, painter):
        for block in self.blocks:
            painter.draw_block(block)

