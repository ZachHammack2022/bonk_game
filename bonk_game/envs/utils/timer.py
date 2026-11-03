"""Round timer with sudden death, so a round can't stall forever.

Each round has a time limit (Map.round_time, in seconds). On maps that
respawn the dead player instead of restarting (Classic), the clock restarts
after every point, so it limits the time between points.

When time runs out, sudden death starts: deadly walls close in from both
sides at a steady speed until they meet in the middle. Anyone whose centre
is past a wall dies, so the player pushed out first loses, and the round
always ends.
"""

STEPS_PER_SECOND = 30  # physics steps per second (see PHYSICS_HZ in the UI)
WALL_SPEED = 1.2       # pixels per step each wall moves inward (36 px/s)


class RoundTimer:
    def __init__(self, limit_seconds, start=(0, 680)):
        """limit_seconds: round length; 0 or None turns the timer off.
        start: (left, right) x where the walls appear when time runs out."""
        self.limit = int(round((limit_seconds or 0) * STEPS_PER_SECOND))
        self.start = start
        self.steps = 0

    @property
    def enabled(self):
        return self.limit > 0

    def reset(self):
        self.steps = 0

    def step(self):
        if self.enabled:
            self.steps += 1

    @property
    def remaining(self):
        """Seconds left before sudden death (0 once it has started)."""
        if not self.enabled:
            return None
        return max(0.0, (self.limit - self.steps) / STEPS_PER_SECOND)

    @property
    def sudden_death(self):
        return self.enabled and self.steps >= self.limit

    def walls(self):
        """(left, right) x of the closing walls, or None before sudden death."""
        if not self.sudden_death:
            return None
        left, right = self.start
        middle = (left + right) / 2
        moved = (self.steps - self.limit) * WALL_SPEED
        return min(left + moved, middle), max(right - moved, middle)

    def kills(self, p):
        w = self.walls()
        return w is not None and not (w[0] < p.x < w[1])
