"""Power-ups for online matches (a room setting, off by default).

Every few seconds a pickup appears somewhere players can spawn (at most
MAX_ON_MAP at once). Touch it to get its effect for a few seconds:

- speed: you push harder and your top speed goes up
- float: gravity pulls you much less (higher jumps, slower falls)
- iron:  you're as heavy as a heavy ball the whole time, but move as if
         you weren't
- punch: the next player you bump goes flying

You hold one effect at a time; a new pickup replaces the old one. Being
knocked out ends it. Pickups (and effects) are cleared between rounds.
"""
import math
import random

from bonk_game.envs.utils import arena

TICK_HZ = 30
SPAWN_GAP = (5.0, 9.0)   # seconds between new pickups (random in this range)
FIRST_SPAWN = 3.0        # seconds into a round before the first one
MAX_ON_MAP = 2
PICKUP_RADIUS = 11       # size of a pickup (touch distance is this plus the ball's radius)
PUNCH_SPEED = 16         # speed a punched player is sent off at

# How each effect changes the ball (also sent to browsers for prediction)
KINDS = {
    "speed": {"title": "Speed", "seconds": 6, "force": 1.6, "max_speed": 1.35, "gravity": 1.0},
    "float": {"title": "Float", "seconds": 6, "force": 1.0, "max_speed": 1.0, "gravity": 0.45},
    "iron": {"title": "Iron", "seconds": 5, "force": 1.0, "max_speed": 1.0, "gravity": 1.0, "pin_heavy": True},
    "punch": {"title": "Punch", "seconds": 10, "force": 1.0, "max_speed": 1.0, "gravity": 1.0},
}


class PowerUps:
    def __init__(self, env, rng=None):
        self.env = env
        self.rng = rng or random.Random()
        self.pickups = []                 # [x, y, kind]
        self.effects = [None] * env.n     # per player: [kind, ticks left] or None
        self.base = [(p.v_range, p.gravity) for p in env.players]
        self.collected = [0] * env.n      # pickups each player grabbed (for awards)
        self.reset_round()

    def reset_round(self):
        self.pickups = []
        self.effects = [None] * self.env.n
        self.next_spawn = FIRST_SPAWN * TICK_HZ
        self.apply()

    # --- each tick ------------------------------------------------------------
    def apply(self):
        """Set every ball's physics for its current effect. Run before each step."""
        for p, eff, (v_range, gravity) in zip(self.env.players, self.effects, self.base):
            k = KINDS[eff[0]] if eff else None
            p.force_mult = k["force"] if k else 1.0
            p.v_range = v_range * (k["max_speed"] if k else 1.0)
            p.gravity = gravity * (k["gravity"] if k else 1.0)
            if k and k.get("pin_heavy"):
                p.m = p.max_m
                p.force_mult *= p.max_m / p.min_m  # heavy, but moves as if it weren't

    def step(self, info):
        """After each physics step. Returns events for the browsers."""
        env = self.env
        events = []
        if info["round_over"]:
            self.reset_round()
            return events
        for victim, _, _ in info["kos"]:
            self.effects[victim] = None

        # Effects run out
        for i, eff in enumerate(self.effects):
            if eff:
                eff[1] -= 1
                if eff[1] <= 0:
                    self.effects[i] = None

        # Punch: the next bump sends the other player flying
        for i, eff in enumerate(self.effects):
            hit = env.last_hit[i]
            if eff and eff[0] == "punch" and hit is not None and hit[1] == env.steps:
                me, them = env.players[i], env.players[hit[0]]
                d = math.hypot(them.x - me.x, them.y - me.y) or 1
                them.x_v = (them.x - me.x) / d * PUNCH_SPEED
                them.y_v = (them.y - me.y) / d * PUNCH_SPEED - 4
                self.effects[i] = None
                events.append({"e": "punch", "i": i, "x": round((me.x + them.x) / 2, 1),
                               "y": round((me.y + them.y) / 2, 1)})

        # Pick up
        for pickup in list(self.pickups):
            x, y, kind = pickup
            for i, p in enumerate(env.players):
                if p.alive and math.hypot(p.x - x, p.y - y) < p.r + PICKUP_RADIUS:
                    self.pickups.remove(pickup)
                    self.effects[i] = [kind, KINDS[kind]["seconds"] * TICK_HZ]
                    self.collected[i] += 1
                    events.append({"e": "pickup", "i": i, "k": kind, "x": round(x, 1), "y": round(y, 1)})
                    break

        # Spawn
        self.next_spawn -= 1
        if self.next_spawn <= 0:
            self.next_spawn = self.rng.uniform(*SPAWN_GAP) * TICK_HZ
            if len(self.pickups) < MAX_ON_MAP:
                spot = self._spot()
                if spot is not None:
                    kind = self.rng.choice(list(KINDS))
                    self.pickups.append([spot[0], spot[1], kind])
                    events.append({"e": "spawn", "k": kind, "x": round(spot[0], 1), "y": round(spot[1], 1)})
        return events

    def _spot(self):
        """Somewhere in the spawn area, away from players and other pickups."""
        box = self.env.map.spawn_box
        taken = [(p.x, p.y) for p in self.env.players if p.alive] + [(x, y) for x, y, _ in self.pickups]
        for _ in range(20):
            x = self.rng.uniform(box[0] + PICKUP_RADIUS, box[1] - PICKUP_RADIUS)
            y = self.rng.uniform(box[2] + PICKUP_RADIUS, box[3] - PICKUP_RADIUS)
            if all(math.hypot(x - a, y - b) > arena.RADIUS * 3 for a, b in taken):
                return x, y
        return None

    def state(self):
        return {
            "pickups": [[round(x, 1), round(y, 1), k] for x, y, k in self.pickups],
            "effects": [None if e is None else [e[0], round(e[1] / TICK_HZ, 1)] for e in self.effects],
        }


def describe():
    """Effect constants for the browsers (prediction and labels)."""
    return {k: dict(v) for k, v in KINDS.items()}
