"""Contains player class and methods"""
import numpy as np

# On jump maps, forgiving jump timing (in physics steps, 30 per second):
JUMP_BUFFER = 4  # an "up" press is remembered this long, then jumps on landing
COYOTE_TIME = 4  # you can still jump this long after leaving the ground

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
        self.gravity = 1.5  # added to the vertical speed every step
        # Power-up multipliers on top of the values above (1 = no effect)
        self.force_mult = 1.0    # push from inputs
        self.speed_mult = 1.0    # top speed
        self.gravity_mult = 1.0  # gravity
        self.grounded = False
        self.jump_buffer = 0     # steps left on a remembered "up" press
        self.air_steps = COYOTE_TIME + 1  # steps since last standing on something
        self.jump_used = False   # jumped since last standing on something
        self.reset()
        self.normalize_obs()

    def update_velocities(self):

        # prepare velocities for normalization
        self.y_v += self.gravity * self.gravity_mult
        cap = self.v_range * self.speed_mult
        self.x_v = max(-cap, min(cap, self.x_v))
        self.y_v = max(-cap, min(cap, self.y_v))


    def update_position(self):

        self.x += self.x_v
        self.y += self.y_v
        if self.clamp_bottom:
            self.y = min(self.bottom-self.r,self.y)

    def update_mass(self):
        if self.m > self.min_m:
            self.m = max(self.m-0.1,self.min_m)

    def make_heavy(self):
        # Can only go heavy again once the previous heavy has fully worn off
        if self.m == self.min_m:
            self.m = self.max_m


    def normalize_obs(self):

        x = self.normalize(self.left,self.right,self.x)
        y = self.normalize(self.top,self.bottom,self.y)
        x_v = self.normalize(-self.v_range,self.v_range,self.x_v)
        y_v = self.normalize(-self.v_range,self.v_range,self.y_v)
        m = self.normalize(self.min_m,self.max_m,self.m)

        # Clip so a player knocked briefly past a wall still fits the obs space
        self._obs = np.clip(np.array([x,y,x_v,y_v,self.alive,m]),-1,1)

    def update(self)-> None:
        """_Update velocity and position values
        """
        if not self.can_fly:
            self.update_jump()
        self.update_velocities()
        self.update_position()
        self.update_mass()


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
        self.grounded = False
        self.jump_buffer = 0
        self.air_steps = COYOTE_TIME + 1
        self.jump_used = False

    def get_obs(self):
        self.normalize_obs()
        return self._obs


    def dies(self):
        """Set alive attribute to False upon death
        """
        self.alive = 0

    def move_up(self,force):
        if self.can_fly:
            self.y_v -= force*self.force_mult/self.m
        else:
            self.jump_buffer = JUMP_BUFFER
            self.try_jump()

    def can_jump(self):
        if self.grounded and self.y_v > -self.jump_speed / 2:
            return True
        return not self.jump_used and self.air_steps <= COYOTE_TIME

    def try_jump(self):
        if self.jump_buffer and self.can_jump():
            self.y_v = min(self.y_v, -self.jump_speed)
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
            self.jump_buffer = max(0, self.jump_buffer - 1)

    def move_down(self,force):
        self.y_v += force*self.force_mult/self.m

    def move_left(self,force):
        self.x_v -= force*self.force_mult/self.m

    def move_right(self,force):
        self.x_v += force*self.force_mult/self.m

    def normalize(self,low,high,val):
        return ((val - low)/(high-low)-0.5)*2

