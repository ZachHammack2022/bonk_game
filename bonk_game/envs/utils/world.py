"""The physics: a Box2D world (https://box2d.org, through pybox2d).

Box2D does the rigid-body work: collisions between balls, platforms, slopes,
bumpers and the moving parts, bounces, friction, the swing's rope and the
sliding platform's rail. The browser runs the same engine (planck.js, a
JavaScript port of Box2D: static/physics.js) to predict your ball, so the
two agree on everything, other balls and moving parts included.

What stays bonk's own is the game rules on top: the speed cap, jumping
(player.py), going heavy, grip on the ground, launch pads and bumpers, and
which contacts kill. They're applied around each Box2D step, here and in
physics.js in the same order.

Units. The rest of the game counts in pixels and "steps": positions in px,
speeds in px per step (1/30 s at normal speed), gravity in px per step per
step. Box2D wants metres and seconds, and works best with things between
0.1 and 10 m, so PPM pixels make a metre (a ball is 1 m across) and a step
is STEP_SECONDS. The game speed (stepping.TIME_SCALE) is how much of a step
passes per tick: everything happens slower, but every path is the same.

The objects outside (players, Blocks, a Swing's theta...) stay the record
of where everything is. Each step their state is written into Box2D, Box2D
moves everything, and the result is read back, so code that moves a ball
by hand (a respawn, a power-up, a test) just sets its x and y.
"""
import math

from Box2D import b2

PPM = 40.0                 # pixels per Box2D metre
STEP_SECONDS = 1 / 30      # one physics step at normal speed (time_scale 1)
SUBSTEPS = 4               # Box2D steps per physics step
VELOCITY_ITERATIONS = 8
POSITION_ITERATIONS = 3
# px per step per step: what a ball feels with no power-ups. Measured from
# bonk.io (a November 2026 recording of the Sinking Swing rebuilt there: the
# ball's fall and the swing's period agree): about 380 px/s^2 at the default
# speed, with balls the size of ours. It used to be 1.5, twice as strong.
GRAVITY = 0.75
# The maps' jump speeds, launch pads and bumpers were made for gravity 1.5.
# They leave at LIFT times their speed, so they reach the same heights as
# they did (a height goes with speed^2 / gravity): the same places are in
# reach, the arcs are just floatier.
TUNED_GRAVITY = 1.5
LIFT = math.sqrt(GRAVITY / TUNED_GRAVITY)
# A surface's "friction" (0-1, from the maps) does two things:
# - Box2D's contact friction is friction * FRICTION_SCALE: what lets a ball
#   ride the swing or shove the sliding platform by rolling on it;
# - grip: while standing on it, a ball's speed over it is damped by
#   friction * GRIP per second (grip() below). That's what stops a ball when
#   you let go and sets how fast you can run on it, as on bonk's original
#   surfaces. In the air nothing slows you.
#   Running (pushing the way you're already going) it grips GRIP_RUNNING
#   instead: you get up to a decent speed, and still stop short when you let
#   go or turn round.
FRICTION_SCALE = 0.5
GRIP = 150.0
GRIP_RUNNING = 30.0
# Moving up faster than this (px per step), a ball has left the ground: grip
# stops at once, so it doesn't take anything off a jump
LIFT_OFF = 2.0
# Collision categories: balls are BALL_BITS; a ghost ball (a power-up)
# doesn't collide with that category, so it passes through the others
BALL_BITS = 0x0002
EVERYTHING = 0xFFFF
# Share of their closing speed two balls bounce apart with (1 would lose
# nothing; bonk.io's balls keep roughly 70-100%)
PLAYER_BOUNCE = 0.85


def to_m(px):
    return px / PPM


def speed_to_b2(v):
    """px per step -> metres per second."""
    return v / PPM / STEP_SECONDS


def speed_from_b2(v):
    return v * PPM * STEP_SECONDS


def accel_to_b2(a):
    """px per step per step -> metres per second per second."""
    return a / PPM / STEP_SECONDS ** 2


def material(m):
    """A surface's settings (a Block's restitution, friction, launch, kill
    and up), for the browser (static/physics.js)."""
    out = {"e": round(m.restitution, 3), "f": round(m.friction, 3)}
    if m.kill:
        out["k"] = 1
    if m.launch is not None:
        out["l"] = round(m.launch * LIFT, 3)
        out["u"] = None if m.up is None else [round(v, 4) for v in m.up]
    return out


class _Contacts(b2.contactListener):
    """Sets each contact's bounce and friction when it starts: balls bounce
    off each other fully and without friction; a ball on a surface gets the
    surface's own (Box2D would otherwise mix the two fixtures' values)."""

    def BeginContact(self, contact):
        a, b = contact.fixtureA.userData, contact.fixtureB.userData
        a_ball, b_ball = isinstance(a, Ball), isinstance(b, Ball)
        if a_ball and b_ball:
            contact.restitution = PLAYER_BOUNCE
            contact.friction = 0.0
        elif a_ball or b_ball:
            surface = b if a_ball else a
            contact.restitution = surface.restitution
            contact.friction = surface.friction * FRICTION_SCALE

    def PostSolve(self, contact, impulse):
        """Remember what each ball hit during the step, even if it bounced
        straight off (then it's no longer touching after the step: a fast
        landing, which Box2D catches mid-step)."""
        a, b = contact.fixtureA.userData, contact.fixtureB.userData
        if not (isinstance(a, Ball) or isinstance(b, Ball)):
            return
        nx, ny = contact_normal(contact)
        if isinstance(b, Ball):
            b.hits.append((a, (nx, ny), contact.fixtureA.body))
        if isinstance(a, Ball):
            a.hits.append((b, (-nx, -ny), contact.fixtureB.body))


class Ball:
    """A player's Box2D body (fixture userData)."""

    def __init__(self, world, p):
        self.p = p
        # A bullet: Box2D stops it passing into moving parts and other balls
        # between substeps (continuous collision), as it does for the level
        self.body = world.CreateDynamicBody(position=(to_m(p.x), to_m(p.y)), fixedRotation=True, bullet=True)
        self.shape = None  # (radius, ghost, group) the fixture was made with
        self._fixture()
        self.mass = None
        self.hits = []  # what it hit in the last Box2D step (see _Contacts.PostSolve)
        self.fall = 0.0  # its downward speed going into this Box2D step (a pogo's landing)
        self.at = None  # (x, y) last read back from Box2D, to spot balls moved by hand

    def _fixture(self):
        """(Re)make the ball's circle for its size, whether it's a ghost,
        and its group (power-ups change all three)."""
        p = self.p
        shape = (p.r, p.ghost, p.group)
        if shape == self.shape:
            return
        for f in list(self.body.fixtures):
            self.body.DestroyFixture(f)
        self.body.CreateCircleFixture(
            radius=to_m(p.r), density=1.0, friction=0.0, restitution=0.0, userData=self,
            categoryBits=BALL_BITS, maskBits=EVERYTHING & ~BALL_BITS if p.ghost else EVERYTHING,
            groupIndex=p.group)
        self.shape = shape
        self.mass = None

    def push(self, active):
        """Write the player's state into the body."""
        body, p = self.body, self.p
        if body.active != active:
            body.active = active
        if not active:
            return
        self._fixture()
        if self.at != (p.x, p.y):
            body.transform = ((to_m(p.x), to_m(p.y)), 0)
        # (A giant is heavier in collisions by its area: pushes still move it
        # as they move anyone, so it isn't slow)
        mass = p.m * (p.r / p.base_r) ** 2
        if self.mass != mass:
            md = body.massData
            md.mass, md.I, md.center = mass, 0.0, (0, 0)
            body.massData = md
            self.mass = mass
        body.gravityScale = p.gravity * p.gravity_mult / GRAVITY
        body.linearVelocity = (speed_to_b2(p.x_v), speed_to_b2(p.y_v))

    def pull(self):
        pos, vel = self.body.position, self.body.linearVelocity
        p = self.p
        p.x, p.y = pos.x * PPM, pos.y * PPM
        p.x_v, p.y_v = speed_from_b2(vel.x), speed_from_b2(vel.y)
        self.at = (p.x, p.y)

    def standing(self):
        """On top of something solid?"""
        return any(not isinstance(other, Ball) and not other.kill and ny < -0.5
                   for other, (_, ny), _ in self.touching())

    def touching(self):
        """(other fixture's userData, normal from it towards this ball, its
        body) for everything the ball is touching, or hit in the last step."""
        seen = set()
        for edge in self.body.contacts:
            c = edge.contact
            if not c.touching:
                continue
            a, b = c.fixtureA.userData, c.fixtureB.userData
            if c.fixtureA.sensor or c.fixtureB.sensor:
                n = (0.0, 0.0)
            else:
                nx, ny = contact_normal(c)  # from A to B
                n = (nx, ny) if b is self else (-nx, -ny)
            other = a if b is self else b
            seen.add(id(other))
            yield other, n, (c.fixtureA if b is self else c.fixtureB).body
        for other, n, body in self.hits:
            if id(other) not in seen:
                seen.add(id(other))
                yield other, n, body


def contact_normal(c):
    """A touching contact's normal, pointing from fixture A to fixture B.

    Worked out from the manifold, as Box2D's b2WorldManifold does (pybox2d's
    worldManifold doesn't always come back filled in). Nothing in bonk's
    worlds rotates, so local directions are world directions."""
    m = c.manifold
    if m.type_ == b2.manifold.e_circles:
        pa = c.fixtureA.body.GetWorldPoint(m.localPoint)
        pb = c.fixtureB.body.GetWorldPoint(m.points[0].localPoint)
        dx, dy = pb.x - pa.x, pb.y - pa.y
        d = math.hypot(dx, dy)
        return (dx / d, dy / d) if d > 1e-9 else (0.0, -1.0)
    nx, ny = m.localNormal
    if m.type_ == b2.manifold.e_faceB:
        return -nx, -ny
    return nx, ny


class World:
    """One map's Box2D world: the level's pieces and moving parts, and a
    ball for each player (made the first time it's stepped)."""

    def __init__(self, blocks=(), parts=()):
        self.b2 = b2.world(gravity=(0, accel_to_b2(GRAVITY)), doSleep=False)
        self.listener = _Contacts()
        self.b2.contactListener = self.listener
        self.ground = self.b2.CreateStaticBody()
        self.blocks = list(blocks)
        for block in self.blocks:
            add_piece(self.ground, block, (0.0, 0.0))
        self.parts = list(parts)
        for part in self.parts:
            part.attach(self.b2, self.ground)
        self.balls = {}
        self._deadly = [f for body in self.b2.bodies for f in body.fixtures if f.sensor]

    def ball(self, p):
        b = self.balls.get(id(p))
        if b is None or b.p is not p:
            b = self.balls[id(p)] = Ball(self.b2, p)
        return b

    def drop(self, p):
        """Take a ball out of the world for good (a swarm copy that's gone)."""
        b = self.balls.pop(id(p), None)
        if b is not None and b.p is p:
            self.b2.DestroyBody(b.body)

    def deadly(self, p):
        """Is player p (where it is now) touching a deadly piece?"""
        if not self._deadly:
            return False
        circle = b2.circleShape(radius=to_m(p.r))
        at = b2.transform()
        at.position = (to_m(p.x), to_m(p.y))
        at.angle = 0
        return any(b2.testOverlap(circle, 0, f.shape, 0, at, f.body.transform) for f in self._deadly)

    def solid_at(self, x, y, r):
        """Does a circle (px) overlap any of the level (not the balls)?"""
        circle = b2.circleShape(radius=to_m(r))
        at = b2.transform()
        at.position = (to_m(x), to_m(y))
        at.angle = 0
        balls = {b.body for b in self.balls.values()}
        return any(b2.testOverlap(circle, 0, f.shape, 0, at, f.body.transform)
                   for body in self.b2.bodies if body not in balls for f in body.fixtures)

    def describe(self):
        """The level as the browser's copy of the physics builds it."""
        return {"static": [piece_spec(b, (0.0, 0.0)) for b in self.blocks],
                "parts": [part.describe() for part in self.parts]}

    def part_states(self):
        """[x, y, x speed, y speed] of each moving part (px, px per step)."""
        return [part.state() for part in self.parts]

    def step(self, movers=(), time_scale=1.0, substeps=SUBSTEPS, on_contact=None):
        """Move everything through one step (`time_scale` of a step at
        normal speed), in `substeps` Box2D steps.

        movers: the players in play; any other player is taken out of the
        world for now (knocked out, or held after a respawn).
        on_contact(i, j) is told about each pair of movers that touch
        (indexes into movers), once per substep.

        A player touching something deadly is marked `doomed` (the env
        knocks them out at the start of the next step); one on top of
        something is `grounded` (they can jump)."""
        movers = list(movers)
        moving = {id(p) for p in movers}
        for key, ball in self.balls.items():
            if key not in moving:
                ball.push(False)
        balls = [self.ball(p) for p in movers]
        index = {id(b): i for i, b in enumerate(balls)}
        for b in balls:
            b.push(True)
        for part in self.parts:
            part.push()
        # Jumping needs to know who's standing on something where they are
        # now: a step of no time brings Box2D's contacts up to date
        self.b2.Step(0, VELOCITY_ITERATIONS, POSITION_ITERATIONS)
        for b in balls:
            b.p.grounded = b.standing()
            b.p.begin_step()
            b.body.linearVelocity = (speed_to_b2(b.p.x_v), speed_to_b2(b.p.y_v))
        dt = time_scale * STEP_SECONDS / substeps
        for _ in range(substeps):
            before = [part.before_substep() for part in self.parts]
            for b in balls:
                b.hits.clear()
                b.fall = b.p.y_v  # (how fast it's coming down, for a pogo on landing)
            self.b2.Step(dt, VELOCITY_ITERATIONS, POSITION_ITERATIONS)
            for part, prev in zip(self.parts, before):
                part.after_substep(prev, dt)
            for b in balls:
                b.pull()
            for i, b in enumerate(balls):
                self._rules(b, i, index, on_contact, dt)
        for p in movers:
            p.end_step()

    def _rules(self, ball, i, index, on_contact, dt):
        """bonk's rules for one ball after a Box2D step of `dt` seconds:
        grounded and grip, launch pads, deadly pieces, contacts with other
        balls, the speed cap."""
        p = ball.p
        p.grounded = False
        ground = None  # what it's standing on with the most grip: (surface, normal, body)
        for other, (nx, ny), body in ball.touching():
            if isinstance(other, Ball):
                j = index.get(id(other))
                if on_contact is not None and j is not None and i < j:
                    on_contact(i, j)
                continue
            if other.kill:
                p.doomed = True
                continue
            if ny < -0.5:
                p.grounded = True  # standing on top of something: can jump
                if ground is None or other.friction > ground[0].friction:
                    ground = (other, (nx, ny), body)
            if other.launch is not None:
                launch(p, other, nx, ny)
        # Grip slows a ball on the ground, but not one leaving it
        if ground is not None and ground[0].friction and p.y_v >= -LIFT_OFF:
            grip(p, *ground, dt)
        if p.grounded and p.jump_buffer and not p.can_fly:
            # "Up" pressed just before landing: jump the moment you land
            # (even if the landing bounces you straight back off), with a
            # pogo from how hard you came down
            p.try_jump(landing=ball.fall)
        cap = p.v_range * p.speed_mult
        p.x_v = max(-cap, min(cap, p.x_v))
        # (Going up, LIFT of it: nothing climbs higher than it did before
        # gravity was halved, a pogo bounce or a pad included)
        p.y_v = max(-cap * LIFT, min(cap, p.y_v))
        if p.clamp_bottom and p.y > p.bottom - p.r:
            p.y = p.bottom - p.r
        ball.body.linearVelocity = (speed_to_b2(p.x_v), speed_to_b2(p.y_v))
        if (p.x, p.y) != ball.at:
            ball.body.transform = ((to_m(p.x), to_m(p.y)), 0)
            ball.at = (p.x, p.y)


def grip(p, surface, normal, body, dt):
    """Grip: a ball standing on a surface slides more and more slowly over
    it (its speed along the surface, relative to the surface, is damped by
    surface.friction * GRIP per second). A surface that moves carries what's
    on it, and one that can be pushed (the sliding platform) is dragged the
    other way: that's how rolling on it rocks it."""
    nx, ny = normal
    tx, ty = -ny, nx
    v = body.linearVelocity
    svx, svy = speed_from_b2(v.x), speed_from_b2(v.y)
    vt = (p.x_v - svx) * tx + (p.y_v - svy) * ty
    g = GRIP_RUNNING if p.run_dir * tx * vt > 0 else GRIP
    dv = vt * (1 - math.exp(-surface.friction * g * dt))
    p.x_v -= dv * tx
    p.y_v -= dv * ty
    if body.type == b2.dynamicBody:
        body.ApplyLinearImpulse((speed_to_b2(dv * tx) * p.m, speed_to_b2(dv * ty) * p.m), body.worldCenter, True)


def launch(p, surface, nx, ny):
    """Fire the ball off a launch pad or bumper at `surface.launch` times
    LIFT (px per step, relative to the surface). Pads fire out of their top
    face, only when landed on; bumpers straight away from where they were hit."""
    speed = surface.launch * LIFT
    up = surface.up
    if up is not None:
        if nx * up[0] + ny * up[1] <= 0.5:
            return
        nx, ny = up
    svx, svy = getattr(surface, "vx", 0.0), getattr(surface, "vy", 0.0)
    vn = (p.x_v - svx) * nx + (p.y_v - svy) * ny
    if vn < speed:
        p.x_v += (speed - vn) * nx
        p.y_v += (speed - vn) * ny


# --- pieces ---------------------------------------------------------------------
def piece_spec(block, origin):
    """A piece's shape relative to `origin` (its body's position, px) and
    its material, for the browser."""
    ox, oy = origin
    if hasattr(block, "radius"):
        shape = {"s": "circle", "c": [block.cx - ox, block.cy - oy], "r": block.radius}
    elif hasattr(block, "angle"):
        shape = {"s": "box", "c": [block.cx - ox, block.cy - oy], "h": [block.w / 2, block.h / 2],
                 "a": math.radians(block.angle)}
    else:
        x1, y1, x2, y2 = block.rect()
        shape = {"s": "box", "c": [(x1 + x2) / 2 - ox, (y1 + y2) / 2 - oy],
                 "h": [(x2 - x1) / 2, (y2 - y1) / 2], "a": 0.0}
    shape["c"] = [round(v, 3) for v in shape["c"]]
    return {**shape, **material(block)}


def add_piece(body, block, origin):
    """Add a Block / OrientedBlock / Bumper to `body` as a fixture. `origin`
    is where the body is (px): the piece's own coordinates are absolute."""
    spec = piece_spec(block, origin)
    cx, cy = to_m(spec["c"][0]), to_m(spec["c"][1])
    opts = dict(friction=block.friction * FRICTION_SCALE, restitution=block.restitution,
                isSensor=bool(block.kill), userData=block, density=1.0)
    if spec["s"] == "circle":
        return body.CreateCircleFixture(radius=to_m(spec["r"]), pos=(cx, cy), **opts)
    hw, hh = spec["h"]
    return body.CreatePolygonFixture(box=(to_m(hw), to_m(hh), (cx, cy), spec["a"]), **opts)


def set_mass(body, mass):
    md = body.massData
    md.mass, md.I, md.center = mass, 0.0, (0, 0)
    body.massData = md
