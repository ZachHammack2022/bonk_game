"""Contains player class and methods"""
import numpy as np

# On jump maps, forgiving jump timing (in physics steps, 30 per second):
JUMP_BUFFER = 4  # an "up" press is remembered this long, then jumps on landing
COYOTE_TIME = 4  # you can still jump this long after leaving the ground
# Pogo: jump as you land and you keep this share of the speed you landed
# with, on top of a normal jump. Up, down (to land hard), then up again
# just before you touch down bounces you far higher; keep it going and
# each bounce climbs, up to the speed cap.
POGO = 0.7

def new_rng(seed=None):
    """Random numbers for one env and its players (where they spawn).

    Without a seed, one is drawn from numpy's global random numbers, once:
    so np.random.seed() still makes things repeatable, but nothing after
    that touches (or is changed by) the global state."""
    return np.random.RandomState(int(np.random.randint(2 ** 31)) if seed is None else seed)


class player():

    def __init__(self,radius,left,right,top,bottom,color,spawn=None,clamp_bottom=True,rng=None) -> None:
        """Create a player.

        Args:
            left/right/top/bottom: area used to normalize observations
            spawn: (left, right, top, bottom) box to spawn in; defaults to the
                observation area
            clamp_bottom: never let the player sink below `bottom` (the
                classic map's floor). Maps where you can fall out turn it off.
            rng: random numbers for spawning (new_rng(); an env shares one
                between its players)
        """
        self.rng = new_rng() if rng is None else rng
        # store env bounds
        self.left = left
        self.right = right
        self.top = top
        self.bottom = bottom
        # store player characteristics
        self.color = color
        self.r = radius
        self.v_range = 20 # velocities are clamped to [-v_range, v_range]
        self.max_m = 5
        self.min_m = 1
        self.score = 0
        # Steps left frozen after a respawn (TestEnv's respawn_hold); 0: playing
        self.held = 0
        self.spawn = spawn if spawn is not None else (left, right, top, bottom)
        self.clamp_bottom = clamp_bottom
        # Classic players fly: "up" is a constant thrust stronger than gravity.
        # Maps can turn that off so "up" is a jump that only works when the
        # player is standing on something (set grounded during collisions).
        self.can_fly = True
        self.jump_speed = 0
        self.push = 2  # sideways and down push from an input (map.push_force)
        self.hover = 0.0  # jump maps: share of gravity "up" cancels in the air
        self.gravity = 0.75  # added to the vertical speed every step (world.GRAVITY)
        # How much of a physics step passes each tick (stepping.TIME_SCALE):
        # scales pushes from inputs and heavy wearing off, as the world scales
        # movement and gravity (world.World.step)
        self.time_scale = 1.0
        # Power-up multipliers on top of the values above (1 = no effect)
        self.force_mult = 1.0    # push from inputs
        self.speed_mult = 1.0    # top speed
        self.gravity_mult = 1.0  # gravity
        # Power-ups that change the ball itself (server/powerups.py; Box2D
        # picks them up in world.Ball.push)
        self.base_r = radius     # its usual size (r is bigger while it's a giant,
                                 # and it's heavier in collisions by the same area)
        self.ghost = False       # passes through other balls (not the level)
        self.group = 0           # balls in the same (negative) group don't touch
        self.grounded = False
        self.jump_buffer = 0     # steps left on a remembered "up" press
        self.air_steps = COYOTE_TIME + 1  # steps since last standing on something
        self.jump_used = False   # jumped since last standing on something
        self.reset()
        self.normalize_obs()

    def make_heavy(self):
        """Heavy for as long as the button's held: from now to the end of
        this step (end_step lets go unless it's pressed again). Pushes are
        divided by your mass, so you move 5x more slowly while heavy."""
        self.m = self.max_m
        self.heavy_held = True


    def normalize_obs(self):

        x = self.normalize(self.left,self.right,self.x)
        y = self.normalize(self.top,self.bottom,self.y)
        x_v = self.normalize(-self.v_range,self.v_range,self.x_v)
        y_v = self.normalize(-self.v_range,self.v_range,self.y_v)
        m = self.normalize(self.min_m,self.max_m,self.m)

        # Clip so a player knocked briefly past a wall still fits the obs space
        self._obs = np.clip(np.array([x,y,x_v,y_v,self.alive,m]),-1,1)

    def begin_step(self):
        """Once a step, before moving: jumping (which needs to know whether
        we're standing on something: `grounded`, set by the physics)."""
        if not self.can_fly:
            self.update_jump()

    def end_step(self):
        """Once a step, at the end: let go of heavy if it wasn't held this
        step, forget which way we ran, and a remembered "up" press counts
        down (it lasts the whole step: landing partway through one fires
        it, world.World.step)."""
        if not self.heavy_held:
            self.m = self.min_m
        self.heavy_held = False
        self.run_dir = 0
        if self.jump_buffer:
            self.jump_buffer -= 1


    def reset(self)->None:
        """Respawn at a random spot inside the arena with no velocity."""
        left, right, top, bottom = self.spawn
        start_width = (right-left-2*self.r-2)
        start_height = (bottom-top-2*self.r-2)

        self.alive = 1.0
        self.held = 0
        self.x = left+ self.r+1+ self.rng.random()*start_width
        self.y = top+ self.r+1+ self.rng.random()*start_height
        self.x_v = 0
        self.y_v = 0
        self.y_a = 0
        self.m = self.min_m
        self.heavy_held = False  # heavy pressed this step (make_heavy)
        # Which way the input pushed this step (-1 left, 1 right, 0 neither):
        # running the way you're going, the ground grips less (world.grip)
        self.run_dir = 0
        self.grounded = False
        self.jump_buffer = 0
        self.air_steps = COYOTE_TIME + 1
        self.jump_used = False
        # Touched something deadly during a step: dies at the start of the
        # next one (see world.World.step)
        self.doomed = False

    def get_obs(self):
        self.normalize_obs()
        return self._obs


    def dies(self):
        """Set alive attribute to False upon death
        """
        self.alive = 0

    def move_up(self,force):
        if self.can_fly:
            self.y_v -= force*self.force_mult*self.time_scale/self.m
        else:
            if not self.grounded and self.hover:
                # Hovering: holding "up" in the air cancels part of gravity
                self.y_v -= (self.hover * self.gravity * self.gravity_mult
                             * self.time_scale / self.m)
            self.jump_buffer = JUMP_BUFFER
            self.try_jump()

    def can_jump(self):
        if self.grounded and self.y_v > -self.jump_speed / 2:
            return True
        return not self.jump_used and self.air_steps <= COYOTE_TIME

    def try_jump(self, landing=None):
        """Jump, if "up" was pressed lately and we can. landing: the speed
        (px per step, downwards) we just hit the ground with, when this is
        a jump on landing (World._rules): it always can, and pogos."""
        if self.jump_buffer and (landing is not None or self.can_jump()):
            boost = POGO * max(0.0, landing or 0.0)
            self.y_v = min(self.y_v, -(self.jump_speed + boost))
            self.grounded = False
            self.jump_used = True
            self.jump_buffer = 0

    def update_jump(self):
        """Track time off the ground and fire a buffered jump on landing.

        Runs after collisions, which set `grounded`. Standing on something
        right after a jump (still moving up fast) doesn't count as landing.
        """
        if self.grounded and self.y_v > -self.jump_speed / 2:
            self.air_steps = 0
            self.jump_used = False
        else:
            self.air_steps += 1
        if self.jump_buffer:
            self.try_jump()

    def move_down(self,force):
        self.y_v += force*self.force_mult*self.time_scale/self.m

    def move_left(self,force):
        self.x_v -= force*self.force_mult*self.time_scale/self.m
        self.run_dir -= int(force > 0) - int(force < 0)

    def move_right(self,force):
        self.x_v += force*self.force_mult*self.time_scale/self.m
        self.run_dir += int(force > 0) - int(force < 0)

    def normalize(self,low,high,val):
        return ((val - low)/(high-low)-0.5)*2

