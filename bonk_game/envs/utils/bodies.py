"""General rigid-body pieces for maps beyond the classic arena.

The classic map keeps its original (floor/ceiling only) collision code in
mechanics.py so agents trained on it behave the same. Newer maps use these:
rectangles that can move, bounce from any side, have friction or launch
players, and a swing that players can knock around and ride.
"""
import math
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

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

    def render(self, canvas):
        rect = pygame.Rect(self.x1, self.y1, self.x2 - self.x1, self.y2 - self.y1)
        pygame.draw.rect(canvas, self.color, rect)


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

    if friction:
        tx, ty = -ny, nx
        vt = rvx * tx + rvy * ty
        p.x_v -= friction * vt * tx
        p.y_v -= friction * vt * ty

    if body is not None:
        body.apply_impulse(-j * nx, -j * ny)
    return j


def collide_block(p, block):
    """Collide a player with a Block. Returns True if the player is killed."""
    rvx, rvy = p.x_v - block.vx, p.y_v - block.vy
    contact = circle_rect_contact(p.x, p.y, p.r, *block.rect(), rvx, rvy)
    if contact is None:
        return False
    if block.kill:
        return True
    resolve_contact(p, contact, (block.vx, block.vy), block.restitution, block.friction)
    nx, ny, _ = contact
    if block.launch is not None and ny < -0.5:
        # Landed on top of a launch pad: fire straight up
        p.y_v = min(p.y_v, block.vy - block.launch)
    return False


class Swing:
    """A pendulum with a cup-shaped seat hanging from a fixed pivot.

    The seat stays level (like a real swing seat) while the ropes swing.
    Players bump it to set it moving, heavier players kick harder, and a
    player sitting in the cup gets carried along with it.
    """

    def __init__(self, pivot_x, pivot_y, length, seat_width=96, lip_height=18,
                 thickness=8, mass=4.0, damping=0.997, max_omega=0.12,
                 restitution=0.15, friction=0.35,
                 color=(139, 90, 43), rope_color=(90, 60, 30)):
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
        self.color = color
        self.rope_color = rope_color
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

    def step(self):
        self.omega -= (GRAVITY / self.length) * math.sin(self.theta)
        self.omega *= self.damping
        self.omega = max(-self.max_omega, min(self.max_omega, self.omega))
        self.theta += self.omega

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

    def render(self, canvas):
        sx, sy = self.seat_pos()
        half = self.seat_width / 2
        for end_x in (sx - half, sx + half):
            pygame.draw.line(canvas, self.rope_color, (self.px, self.py), (end_x, sy - self.lip_height), 3)
        pygame.draw.circle(canvas, self.rope_color, (self.px, self.py), 6)
        for x1, y1, x2, y2 in self.rects():
            pygame.draw.rect(canvas, self.color, pygame.Rect(x1, y1, x2 - x1, y2 - y1))
