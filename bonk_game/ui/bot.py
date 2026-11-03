"""A simple built-in opponent, so you can play solo without training agents.

It doesn't learn anything. It tries to get on the "inside" of its opponent
(between them and the middle of the map) and shove outward, goes heavy just
before impact, jumps after opponents who are above it, and heads for the
swing when the floor starts sinking.

It comes in three difficulty levels (LEVELS).
"""
import math
import random

from bonk_game.envs.utils.arena import ACTIONS, FORCE

_LOOKUP = {(int(dx), int(dy), int(h)): a for a, (dx, dy, h) in ACTIONS.items()}


def action_for(dx, dy, heavy, rng=random):
    """Discrete action for a direction (-1/0/1 each) plus heavy flag."""
    if dx == 0 and dy == 0:
        dx = rng.choice((-1, 1))  # there's no "do nothing" action
    return _LOOKUP[(dx, dy, int(heavy))]


# What changes between difficulty levels:
#   reaction:  chance per step of re-thinking (otherwise repeats its last move)
#   aim_error: random error (px) in where it lines up to push you
#   heavy_chance, heavy_closing: chance it goes heavy when it should, and
#              how fast it must be closing in on you to bother
#   caution:   how wide a margin it keeps from deadly edges, and how early
#              it brakes
#   hop:       chance per step of a surprise hop when close
#   defend:    goes heavy to meet a heavy opponent's charge
# Tuned so each level beats the one below it about 70-80% of the time
# (see tests/test_bot_levels.py and the PR for #11).
LEVELS = {
    "easy": dict(reaction=0.5, aim_error=30, heavy_chance=0.3, heavy_closing=4.0,
                 caution=0.55, hop=0.01, defend=False),
    "medium": dict(reaction=0.7, aim_error=14, heavy_chance=0.55, heavy_closing=3.0,
                   caution=0.8, hop=0.04, defend=False),
    # The original bot, plus bracing for heavy hits
    "hard": dict(reaction=0.85, aim_error=0, heavy_chance=1.0, heavy_closing=2.5,
                 caution=1.0, hop=0.04, defend=True),
}
LEVEL_NAMES = tuple(LEVELS)


class Bot:
    """Drop-in for a trained agent: has predict(obs) -> (action, state)."""

    def __init__(self, env, index, level="medium", reaction=None, rng=None):
        """level: "easy", "medium" or "hard" (see LEVELS). rng: the bot's own
        random numbers (a random.Random; None: one seeded from Python's
        global random numbers, so random.seed() still makes bots repeatable)."""
        if level not in LEVELS:
            raise ValueError(f"Unknown bot level {level!r}. Choose from: {', '.join(LEVELS)}")
        self.env = env
        self.index = index
        self.level = level
        self.rng = random.Random(random.getrandbits(32)) if rng is None else rng
        for k, v in LEVELS[level].items():
            setattr(self, k, v)
        if reaction is not None:
            self.reaction = reaction
        self.aim = 0.0  # current aiming error, changes now and then
        self.last = 0

    def _act(self, dx, dy, heavy):
        return action_for(dx, dy, heavy, self.rng)

    @property
    def me(self):
        return self.env.players[self.index]

    @property
    def them(self):
        """The opponent to go after: the nearest one still in the round."""
        env = self.env
        if hasattr(env, "nearest_opponent"):
            return env.players[env.nearest_opponent(self.index)]
        return env.players[1 - self.index]  # the 1v1 training env

    def predict(self, obs, *args, **kwargs):
        if self.rng.random() > self.reaction:
            return self.last, None
        self.last = self.think()
        return self.last, None

    def walls(self):
        timer = getattr(self.env, "timer", None)
        return timer.walls() if timer is not None else None

    # ------------------------------------------------------------------
    def think(self):
        m = self.env.map
        me, them = self.me, self.them
        lo, hi = m.safe_x_range()
        walls = self.walls()
        if walls is not None:
            # Sudden death: the walls are the new edges
            lo, hi = max(lo, walls[0] + me.r), min(hi, walls[1] - me.r)
            if lo > hi:
                lo = hi = (walls[0] + walls[1]) / 2
        centre = (lo + hi) / 2

        if not me.can_fly and hasattr(m, "swing") and m.steps > m.SINK_DELAY - 45:
            return self.go_to_swing(m)

        # Aim for the side of the opponent closer to the middle, then push out
        them_x = them.x
        side = 1 if them_x < centre else -1
        if self.aim_error and self.rng.random() < 0.05:
            self.aim = self.rng.uniform(-self.aim_error, self.aim_error)
        target_x = them_x + side * (me.r + them.r) * 0.6 + self.aim
        margin = max(me.r, m.bot_margin * self.caution)
        target_x = min(max(target_x, lo + margin), hi - margin)
        dx = target_x - me.x
        if abs(dx) < 4:
            dx = them.x - me.x
        xdir = 0 if abs(dx) < 3 else (1 if dx > 0 else -1)

        # Don't run off the edge chasing: brake if we couldn't stop in time.
        # Braking is weaker while heavy (force / mass).
        decel = FORCE / me.m
        stop = me.x + math.copysign(me.x_v ** 2 / (2 * decel), me.x_v) * self.caution + me.x_v * 2
        braking = False
        if me.x_v > 0 and stop > hi - margin + me.r:
            xdir, braking = -1, True
        elif me.x_v < 0 and stop < lo + margin - me.r:
            xdir, braking = 1, True

        ydir = 0
        if me.can_fly:
            dy = them.y - me.y
            ydir = 1 if dy > 12 else -1 if dy < -12 else (-1 if me.y_v > 1 else 0)
        elif me.grounded and (
                (them.y < me.y - 50 and abs(them.x - me.x) < 140)
                # Now and then hop in close, to hit from above or pop them
                # over an obstacle
                or (abs(them.x - me.x) < 90 and self.rng.random() < self.hop)):
            ydir = -1
        elif not me.grounded and (me.x < lo or me.x > hi):
            # Off the edge: jump is gone, steer back hard
            xdir = 1 if me.x < centre else -1

        dist = math.hypot(them.x - me.x, them.y - me.y)
        closing = ((them.x - me.x) * (me.x_v - them.x_v) + (them.y - me.y) * (me.y_v - them.y_v)) / max(dist, 1)
        # Being heavy makes braking 5x weaker, so stay light near deadly edges
        near_edge = min(me.x - lo, hi - me.x) < margin + 90
        heavy = (dist < 75 and closing > self.heavy_closing and not braking
                 and not (near_edge and m.bot_margin > 20))
        them_heavy = them.m > them.min_m + 1
        if self.defend and them_heavy and dist < 90 and closing > 1 and not braking:
            # They're coming in heavy: meet them heavy so we don't get bowled over
            heavy = True
        if heavy and self.heavy_chance < 1 and self.rng.random() > self.heavy_chance:
            heavy = False
        return self._act(xdir, ydir, heavy)

    def go_to_swing(self, m):
        me = self.me
        sx, sy = m.swing.seat_pos()
        in_seat = abs(me.x - sx) < m.swing.seat_width / 2 and sy - 2 * me.r < me.y < sy + 2
        if in_seat:
            xdir = 0 if abs(me.x - sx) < 6 else (1 if sx > me.x else -1)
            return self._act(xdir, 0, False)
        approach = sx - 110 if me.x < sx else sx + 110
        if me.y > sy and me.grounded:
            if abs(me.x - approach) < 15:
                return self._act(1 if sx > me.x else -1, -1, False)
            return self._act(1 if approach > me.x else -1, 0, False)
        # In the air: steer gently toward the seat
        xdir = 0
        if me.x < sx - 3 and me.x_v < 4:
            xdir = 1
        elif me.x > sx + 3 and me.x_v > -4:
            xdir = -1
        return self._act(xdir, 1 if xdir == 0 and me.y < sy - 30 else 0, False)
