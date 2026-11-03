"""Contains player class and methods"""
import numpy as np

class player():
    
    def __init__(self,radius,left,right,top,bottom,color,spawn=None,clamp_bottom=True) -> None:
        """Create a player.

        Args:
            left/right/top/bottom: area used to normalize observations
            spawn: (left, right, top, bottom) box to spawn in; defaults to the
                observation area
            clamp_bottom: never let the player sink below `bottom` (the
                classic map's floor). Maps where you can fall out turn it off.
        """
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
        self.spawn = spawn if spawn is not None else (left, right, top, bottom)
        self.clamp_bottom = clamp_bottom
        # Classic players fly: "up" is a constant thrust stronger than gravity.
        # Maps can turn that off so "up" is a jump that only works when the
        # player is standing on something (set grounded during collisions).
        self.can_fly = True
        self.jump_speed = 0
        self.grounded = False
        self.reset()
        self.normalize_obs()

    def update_velocities(self):
        
        # prepare velocities for normalization
        self.y_v +=1.5
        if self.x_v >self.v_range:
            self.x_v = self.v_range
        if self.x_v <-self.v_range:
            self.x_v = -self.v_range
        if self.y_v >self.v_range:
            self.y_v = self.v_range
        if self.y_v <-self.v_range:
            self.y_v = -self.v_range
            
    
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
        
        self.update_velocities()
        self.update_position()
        self.update_mass()
        
    
    def reset(self)->None:
        """Respawn at a random spot inside the arena with no velocity."""
        left, right, top, bottom = self.spawn
        start_width = (right-left-2*self.r-2)
        start_height = (bottom-top-2*self.r-2)

        self.alive = 1.0
        self.x = left+ self.r+1+ np.random.random()*start_width
        self.y = top+ self.r+1+ np.random.random()*start_height
        self.x_v = 0
        self.y_v = 0
        self.y_a = 0
        self.m = self.min_m
        self.grounded = False

    def get_obs(self):
        self.normalize_obs()
        return self._obs
    
        
    def dies(self):
        """Set alive attribute to False upon death
        """
        self.alive = 0
    
    def move_up(self,force):
        if self.can_fly:
            self.y_v -= force/self.m
        elif self.grounded:
            self.y_v = min(self.y_v, -self.jump_speed)
            self.grounded = False
    
    def move_down(self,force):
        self.y_v += force/self.m
    
    def move_left(self,force):
        self.x_v -= force/self.m
    
    def move_right(self,force):
        self.x_v += force/self.m
        
    def normalize(self,low,high,val):
        return ((val - low)/(high-low)-0.5)*2

        