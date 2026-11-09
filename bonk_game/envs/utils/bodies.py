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
    """A seat hanging from a pivot, as bonk.io makes one: two wooden planks
    leaning apart in a V, joined rigidly to a pivot far above (a Box2D
    revolute joint, like bonk's "rotating" joint). The whole thing is one
    stiff pendulum: the seat tilts with the rope as it swings.

    There's no floor to the seat: the gap between the planks' feet is a bit
    narrower than a ball, so a ball wedges in and pokes out underneath.

    It swings freely, back and forth like any pendulum: a push or a ball
    landing in it sets it going, and it keeps going on its own. A small
    friction on the joint (a Box2D motor holding it with a little torque)
    takes a ride on it down slowly, over about a minute, and lets an empty
    seat settle back in the middle.

    Measured from bonk.io (a recording of the Sinking Swing rebuilt there,
    November 2026): a 500 px rope swings in about 7.3 s at the default speed
    (ours: 7.35 s); planks 60 x 9.5 px leaning 10 degrees, 57 px apart.

    Args:
        pivot_x, pivot_y: the pivot (px; it can be off the screen)
        length: from the pivot down to the middle of the seat
        seat_width: how wide the V opens at the top (px). The feet stay a
            ball-catching gap apart; a wider seat leans its planks out more.
        mass: the seat's mass, in balls (bonk's density 0.3 wood: 0.27)
        restitution, friction: the planks' (bonk's: bounciness 0, and its
            friction 0.5 is off for players, "Fric Players: No")
        friction_torque: the joint's friction (Box2D N m). 2: a ride
            swinging 20 degrees out is still swinging 7 degrees out after
            40 s; an empty seat stops within 2 degrees of the middle
    """

    kind = "swing"

    PLANK_LENGTH = 60
    PLANK_THICKNESS = 9.5
    FOOT_GAP = 37  # between the planks' feet: a ball (40 across) wedges in
    DEFAULT_WIDTH = 77  # (bonk's: planks leaning 10 degrees)

    def __init__(self, pivot_x, pivot_y, length, seat_width=DEFAULT_WIDTH, mass=0.27,
                 friction_torque=2.0, restitution=0.0, friction=0.04, max_omega=0.12):
        self.px, self.py = pivot_x, pivot_y
        self.length = length
        self.seat_width = seat_width
        self.mass = mass
        self.friction_torque = friction_torque
        self.restitution = restitution
        self.friction = friction
        # Not a limit any more: what the swing's speed is measured against
        # in observations (rad per step)
        self.max_omega = max_omega
        self.lean = self._lean(seat_width)
        a = math.radians(self.lean)
        # Each plank's centre, either side of the seat's middle
        self.plank_offset = (self.FOOT_GAP / 2 + self.PLANK_LENGTH / 2 * math.sin(a)
                       + self.PLANK_THICKNESS / 2 * math.cos(a))
        self.reset()

    @classmethod
    def _lean(cls, width):
        """How far each plank leans out (degrees) for the top to open
        `width` px, the feet staying FOOT_GAP apart."""
        L, t = cls.PLANK_LENGTH, cls.PLANK_THICKNESS
        lo, hi = -10.0, 60.0
        for _ in range(60):
            mid = (lo + hi) / 2
            a = math.radians(mid)
            if cls.FOOT_GAP + 2 * L * math.sin(a) + 2 * t * math.cos(a) < width:
                lo = mid
            else:
                hi = mid
        return lo

    def reset(self):
        self.theta = 0.0  # angle of the rope from straight down (radians)
        self.omega = 0.0  # angular velocity (radians per step)

    # --- kinematics ---------------------------------------------------
    def seat_pos(self):
        """The middle of the seat (between the planks)."""
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
    def planks(self, theta=None):
        """The two planks where they are now (OrientedBlocks), tilted with
        the rope."""
        from bonk_game.ui import theme
        theta = self.theta if theta is None else theta
        sx, sy = self.seat_pos() if theta == self.theta else (
            self.px + self.length * math.sin(theta), self.py + self.length * math.cos(theta))
        c, s = math.cos(theta), math.sin(theta)
        out = []
        for side in (-1, 1):
            # (The seat turns by -theta on screen: a point (x, y) from its
            # middle goes to (x cos + y sin, -x sin + y cos))
            x = side * self.plank_offset
            out.append(OrientedBlock(sx + x * c, sy - x * s, self.PLANK_THICKNESS, self.PLANK_LENGTH,
                                     side * self.lean - math.degrees(theta), theme.WOOD,
                                     restitution=self.restitution, friction=self.friction))
        return out

    def attach(self, world, ground):
        from Box2D import b2
        sx, sy = self.seat_pos()
        self.body = world.CreateDynamicBody(position=(to_m(sx), to_m(sy)), angle=-self.theta)
        seat = self.planks(0.0)
        rest = (self.px, self.py + self.length)
        for piece in seat:
            add_piece(self.body, piece, rest)
        self._pieces = [piece_spec(piece, rest) for piece in seat]
        # Mass as given, spread as the planks are (Box2D's inertia for
        # density 1, scaled)
        md = self.body.massData
        self.inertia = md.I * self.mass / md.mass
        md.mass, md.I, md.center = self.mass, self.inertia, (0, 0)
        self.body.massData = md
        self.joint = world.CreateRevoluteJoint(
            bodyA=ground, bodyB=self.body, anchor=(to_m(self.px), to_m(self.py)),
            enableMotor=True, motorSpeed=0.0, maxMotorTorque=self.friction_torque)
        assert isinstance(self.joint, b2.revoluteJoint)
        self._at = self._attached = (sx, sy)
        self._known = (self.theta, 0.0)  # (a swing set going by hand gets its speed in push)

    def push(self):
        # Only if something set theta or omega by hand since we read them:
        # a body that's being pushed around mid-swing (by a ball's grip, say)
        # isn't quite turning about the pivot yet, and the joint sorts that
        # out over the next steps, here and in the browser (physics.js sets
        # the seat once, from the server's state)
        if self._known == (self.theta, self.omega):
            return
        x, y = self.x_y()
        self.body.transform = ((to_m(x), to_m(y)), -self.theta)
        vx, vy = self.velocity()
        self.body.linearVelocity = (speed_to_b2(vx), speed_to_b2(vy))
        self.body.angularVelocity = -self.omega / STEP_SECONDS
        self._known = (self.theta, self.omega)

    def describe(self):
        return {"kind": self.kind, "at": [round(v, 3) for v in self._attached],
                "pivot": [self.px, self.py], "length": self.length,
                "mass": self.mass, "inertia": round(self.inertia, 6),
                "friction_torque": self.friction_torque, "pieces": self._pieces}

    def after_substep(self, _):
        x, y, vx, vy = self._read()
        self.theta = math.atan2(x - self.px, y - self.py)
        tx, ty = self.tangent()
        self.omega = (vx * tx + vy * ty) / self.length
        self._at = self.seat_pos()
        self._known = (self.theta, self.omega)

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

