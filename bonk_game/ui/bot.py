"""A simple built-in opponent, so you can play solo without training agents.

It doesn't learn anything. It tries to get on the "inside" of its opponent
(between them and the middle of the map) and shove outward, goes heavy just
before impact, jumps after opponents who are above it, and heads for the
swing when the floor starts sinking.
"""
import math
import random

from bonk_game.envs.utils.arena import ACTIONS, FORCE

_LOOKUP = {(int(dx), int(dy), int(h)): a for a, (dx, dy, h) in ACTIONS.items()}


def action_for(dx, dy, heavy):
    """Discrete action for a direction (-1/0/1 each) plus heavy flag."""
    if dx == 0 and dy == 0:
        dx = random.choice((-1, 1))  # there's no "do nothing" action
    return _LOOKUP[(dx, dy, int(heavy))]


class Bot:
    """Drop-in for a trained agent: has predict(obs) -> (action, state)."""

    def __init__(self, env, index, reaction=0.85):
        self.env = env
        self.index = index
        self.reaction = reaction  # chance per step of re-thinking
        self.last = 0

    @property
    def me(self):
        return self.env.players[self.index]

    @property
    def them(self):
        return self.env.players[1 - self.index]

    def predict(self, obs, *args, **kwargs):
        if random.random() > self.reaction:
            return self.last, None
        self.last = self.think()
        return self.last, None

    # ------------------------------------------------------------------
    def think(self):
        m = self.env.map
        me, them = self.me, self.them
        lo, hi = m.safe_x_range()
        centre = (lo + hi) / 2

        if not me.can_fly and hasattr(m, "swing") and m.steps > m.SINK_DELAY - 45:
            return self.go_to_swing(m)

        # Aim for the side of the opponent closer to the middle, then push out
        side = 1 if them.x < centre else -1
        target_x = them.x + side * (me.r + them.r) * 0.6
        margin = max(me.r, m.bot_margin)
        target_x = min(max(target_x, lo + margin), hi - margin)
        dx = target_x - me.x
        if abs(dx) < 4:
            dx = them.x - me.x
        xdir = 0 if abs(dx) < 3 else (1 if dx > 0 else -1)

        # Don't run off the edge chasing: brake if we couldn't stop in time.
        # Braking is weaker while heavy (force / mass).
        decel = FORCE / me.m
        stop = me.x + math.copysign(me.x_v ** 2 / (2 * decel), me.x_v) + me.x_v * 2
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
                or (abs(them.x - me.x) < 90 and random.random() < 0.04)):
            ydir = -1
        elif not me.grounded and (me.x < lo or me.x > hi):
            # Off the edge: jump is gone, steer back hard
            xdir = 1 if me.x < centre else -1

        dist = math.hypot(them.x - me.x, them.y - me.y)
        closing = ((them.x - me.x) * (me.x_v - them.x_v) + (them.y - me.y) * (me.y_v - them.y_v)) / max(dist, 1)
        # Being heavy makes braking 5x weaker, so stay light near deadly edges
        near_edge = min(me.x - lo, hi - me.x) < margin + 90
        heavy = dist < 75 and closing > 2.5 and not braking and not (near_edge and m.bot_margin > 20)
        return action_for(xdir, ydir, heavy)

    def go_to_swing(self, m):
        me = self.me
        sx, sy = m.swing.seat_pos()
        in_seat = abs(me.x - sx) < m.swing.seat_width / 2 and sy - 2 * me.r < me.y < sy + 2
        if in_seat:
            xdir = 0 if abs(me.x - sx) < 6 else (1 if sx > me.x else -1)
            return action_for(xdir, 0, False)
        approach = sx - 110 if me.x < sx else sx + 110
        if me.y > sy and me.grounded:
            if abs(me.x - approach) < 15:
                return action_for(1 if sx > me.x else -1, -1, False)
            return action_for(1 if approach > me.x else -1, 0, False)
        # In the air: steer gently toward the seat
        xdir = 0
        if me.x < sx - 3 and me.x_v < 4:
            xdir = 1
        elif me.x > sx + 3 and me.x_v > -4:
            xdir = -1
        return action_for(xdir, 1 if xdir == 0 and me.y < sy - 30 else 0, False)
