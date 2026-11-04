"""General rigid-body pieces for maps beyond the classic arena.

The classic map keeps its original (floor/ceiling only) collision code in
mechanics.py so agents trained on it behave the same. Newer maps use these:
rectangles that can move, bounce from any side, have friction or launch
players, and a swing that players can knock around and ride.
"""
import math

GRAVITY = 1.5  # matches the per-step gravity players feel in player.py


def circle_rect_contact(cx, cy, r, x1, y1, x2, y2, vx=0.0, vy=0.0):
    """Contact between a circle and an axis-aligned rectangle.

    Returns (nx, ny, depth): the unit normal pointing from the rectangle to
    the circle and how far the circle must move along it to stop
    overlapping. Returns None if they don't touch. (vx, vy) is the circle's
    velocity relative to the rectangle; it's used to pick the face the circle
    came in through if its centre has already ended up inside.
    """
    qx = min(max(cx, x1), x2)
    qy = min(max(cy, y1), y2)
    dx, dy = cx - qx, cy - qy
    d2 = dx * dx + dy * dy
    if d2 > r * r:
        return None
    if d2 > 1e-12:
        d = math.sqrt(d2)
        return dx / d, dy / d, r - d

    # Centre is inside the rectangle: push out through the nearest face the
    # circle was moving into, so fast players don't pop out the far side.
    faces = [(-1, 0, cx - x1), (1, 0, x2 - cx), (0, -1, cy - y1), (0, 1, y2 - cy)]
    entering = [f for f in faces if f[0] * vx + f[1] * vy <= 0] or faces
    nx, ny, dist = min(entering, key=lambda f: f[2])
    return nx, ny, dist + r


class Block:
    """A rectangle players collide with.

    Args:
        restitution: how much of the impact speed is bounced back (0-1)
        friction: fraction of sliding speed (relative to the block) removed
            on each contact
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

    def contact(self, p, rvx, rvy):
        return circle_rect_contact(p.x, p.y, p.r, *self.rect(), rvx, rvy)

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

    def to_local(self, x, y):
        """World vector -> the block's own frame (unrotated)."""
        return x * self.cos + y * self.sin, -x * self.sin + y * self.cos

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

    def contact(self, p, rvx, rvy):
        lx, ly = self.to_local(p.x - self.cx, p.y - self.cy)
        lvx, lvy = self.to_local(rvx, rvy)
        hw, hh = self.w / 2, self.h / 2
        c = circle_rect_contact(lx, ly, p.r, -hw, -hh, hw, hh, lvx, lvy)
        if c is None:
            return None
        nx, ny = self.to_world(c[0], c[1])
        return nx, ny, c[2]


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

    def contact(self, p, rvx, rvy):
        dx, dy = p.x - self.cx, p.y - self.cy
        d = math.hypot(dx, dy)
        reach = p.r + self.radius
        if d >= reach:
            return None
        if d < 1e-9:
            # Dead centre: push back the way it came in
            sp = math.hypot(rvx, rvy)
            dx, dy, d = (-rvx / sp, -rvy / sp, 1.0) if sp > 1e-9 else (0.0, -1.0, 1.0)
            return dx, dy, reach
        return dx / d, dy / d, reach - d


def resolve_contact(p, contact, surface_v=(0.0, 0.0), restitution=0.5,
                    friction=0.0, body=None):
    """Push player `p` out of a surface and bounce it.

    `body` is an optional movable object (e.g. a Swing) that receives the
    equal and opposite impulse. Returns the impulse magnitude.
    """
    nx, ny, depth = contact
    p.x += nx * depth
    p.y += ny * depth
    if ny < -0.5:
        p.grounded = True  # standing on top of something: can jump

    rvx = p.x_v - surface_v[0]
    rvy = p.y_v - surface_v[1]
    vn = rvx * nx + rvy * ny
    if vn >= 0:
        return 0.0  # already separating

    inv_p = 1.0 / p.m
    inv_b = body.inv_mass_along(nx, ny) if body is not None else 0.0
    j = -(1 + restitution) * vn / (inv_p + inv_b)
    p.x_v += j * inv_p * nx
    p.y_v += j * inv_p * ny

    if body is not None:
        body.apply_impulse(-j * nx, -j * ny)

    if friction:
        # Friction drags the player's sliding speed toward the surface's.
        # A movable body gets dragged the other way, which is what lets
        # players shove a sliding platform around by rolling on it.
        tx, ty = -ny, nx
        vt = rvx * tx + rvy * ty
        inv_bt = body.inv_mass_along(tx, ty) if body is not None else 0.0
        jt = friction * vt / (inv_p + inv_bt)  # tangential impulse size
        p.x_v -= jt * inv_p * tx
        p.y_v -= jt * inv_p * ty
        if body is not None:
            body.apply_impulse(jt * tx, jt * ty)
    return j


def collide_block(p, block, body=None):
    """Collide a player with a Block. Returns True if the player is killed.

    `body` is the movable object the block belongs to, if any, so it can
    be pushed back.
    """
    rvx, rvy = p.x_v - block.vx, p.y_v - block.vy
    contact = block.contact(p, rvx, rvy)
    if contact is None:
        return False
    if block.kill:
        return True
    resolve_contact(p, contact, (block.vx, block.vy), block.restitution,
                    block.friction, body=body)
    nx, ny, _ = contact
    if block.launch is not None:
        up = block.up
        if up is None:
            # Bumper: fire away from it along the contact normal
            launch(p, block, nx, ny)
        elif nx * up[0] + ny * up[1] > 0.5:
            # Landed on the pad's top face: fire out of it
            launch(p, block, *up)
    return False


def launch(p, block, nx, ny):
    """Make the player leave the block along (nx, ny) at least at block.launch."""
    if (nx, ny) == (0.0, -1.0):
        # Flat pad (the common case): straight up, exactly as before
        p.y_v = min(p.y_v, block.vy - block.launch)
        return
    vn = (p.x_v - block.vx) * nx + (p.y_v - block.vy) * ny
    if vn < block.launch:
        p.x_v += (block.launch - vn) * nx
        p.y_v += (block.launch - vn) * ny


class SlidingPlatform:
    """A group of blocks that slides left/right as one heavy body.

    It only moves horizontally (as if on a rail): players hitting it or
    rolling on it push it, and it pushes them back. It slowly comes to a
    stop and bounces softly off the ends of its rail.

    Args:
        blocks: the Blocks that make up the platform, at their start positions
        mass: compared to a player's mass of 1 (5 when heavy)
        travel: how far it may slide either way from where it starts
    """

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

    def inv_mass_along(self, nx, ny):
        # Only the horizontal part of a push can move it
        return nx * nx / self.mass

    def apply_impulse(self, jx, jy):
        self.vx += jx / self.mass
        self.vx = max(-self.max_speed, min(self.max_speed, self.vx))

    def step(self, dt=1.0):
        """Slide for `dt` of a step (a substep: see stepping.py)."""
        self.vx *= self.damping ** dt
        new_offset = self.offset + self.vx * dt
        if abs(new_offset) > self.travel:
            # Hit the end of the rail: stop there and bounce back a little
            new_offset = math.copysign(self.travel, new_offset)
            self.vx = -self.vx * self.end_bounce
        dx = new_offset - self.offset
        self.offset = new_offset
        for block in self.blocks:
            block.move(dx, 0)
            block.vx = self.vx

    def collide(self, p):
        """Collide a player with every part. True if a kill block was hit."""
        return any([collide_block(p, block, body=self) for block in self.blocks])

    def render(self, painter):
        # Angled pieces first, so flat ones cover their feet
        for block in sorted(self.blocks, key=lambda b: not hasattr(b, "angle")):
            painter.draw_block(block)


class Swing:
    """A pendulum with a cup-shaped seat hanging from a fixed pivot.

    The seat stays level (like a real swing seat) while the ropes swing.
    Players bump it to set it moving, heavier players kick harder, and a
    player sitting in the cup gets carried along with it.
    """

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
        self.theta = 0.0  # angle of the ropes from straight down (radians)
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

    # --- dynamics -----------------------------------------------------
    def inv_mass_along(self, nx, ny):
        """Inverse mass the swing presents to a push along (nx, ny).

        The seat can only move along its tangent, so a push straight along
        the ropes doesn't move it at all.
        """
        tx, ty = self.tangent()
        return (tx * nx + ty * ny) ** 2 / self.mass

    def apply_impulse(self, jx, jy):
        tx, ty = self.tangent()
        self.omega += (jx * tx + jy * ty) / (self.mass * self.length)
        self.omega = max(-self.max_omega, min(self.max_omega, self.omega))

    def step(self, dt=1.0):
        """Swing for `dt` of a step (a substep: see stepping.py)."""
        self.omega -= (GRAVITY / self.length) * math.sin(self.theta) * dt
        self.omega *= self.damping ** dt
        self.omega = max(-self.max_omega, min(self.max_omega, self.omega))
        self.theta += self.omega * dt

    # --- shape --------------------------------------------------------
    def rects(self):
        """Seat base and the two lips that make it a cup, as (x1, y1, x2, y2)."""
        sx, sy = self.seat_pos()
        half, t, lip = self.seat_width / 2, self.thickness, self.lip_height
        base = (sx - half, sy, sx + half, sy + t)
        left_lip = (sx - half, sy - lip, sx - half + t, sy)
        right_lip = (sx + half - t, sy - lip, sx + half, sy)
        return [base, left_lip, right_lip]

    def collide(self, p):
        """Collide a player with the seat."""
        svx, svy = self.velocity()
        for rect in self.rects():
            contact = circle_rect_contact(p.x, p.y, p.r, *rect, p.x_v - svx, p.y_v - svy)
            if contact is not None:
                resolve_contact(p, contact, (svx, svy), self.restitution,
                                self.friction, body=self)
                svx, svy = self.velocity()

    def render(self, painter):
        painter.swing(self)
