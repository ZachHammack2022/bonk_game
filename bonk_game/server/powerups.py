"""Power-ups for online matches (a room setting, off by default).

Every few seconds a pickup appears somewhere players can spawn (at most
MAX_ON_MAP at once). Touch it to get its effect for a few seconds:

- speed: you push harder and your top speed goes up
- float: gravity pulls you much less (higher jumps, slower falls)
- iron:  you're as heavy as a heavy ball the whole time, but move as if
         you weren't
- punch: the next player you bump goes flying
- plane: the super power-up (rarer). The match freezes for a moment while
         everyone watches you jump into an attack plane; then you fly
         along the top of the map for PLANE_SECONDS, out of play (nothing
         can hit you), steering left and right and dropping BOMBS bombs.
         A bomb goes off when it hits a ball or the level, knocking out
         everyone (but you and your team) within BLAST. Then you're back
         where you were.

The room picks which of these can turn up (`kinds`). You hold one effect
at a time; a new pickup replaces the old one. Being knocked out ends it.
Pickups (and effects, and a plane) are cleared between rounds.
"""
import math
import random

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.controls import Buttons

TICK_HZ = 30
SPAWN_GAP = (5.0, 9.0)   # seconds between new pickups (random in this range)
FIRST_SPAWN = 3.0        # seconds into a round before the first one
MAX_ON_MAP = 2
PICKUP_RADIUS = 11       # size of a pickup (touch distance is this plus the ball's radius)
PUNCH_SPEED = 16         # speed a punched player is sent off at

# The attack plane (times in seconds, distances in px, speeds in px a
# physics step, like the balls')
SUPER = "plane"
INTRO_SECONDS = 2.4      # the match stands still for the cutscene
PLANE_SECONDS = 10
PLANE_Y = 82             # how far down from the top it flies (below the scoreboard;
                         # lower on a map with a ceiling)
PLANE_SPEED = 8
PLANE_MARGIN = 26        # how close to the sides it can go
BOMBS = 2
BOMB_GAP = 0.4           # seconds between bombs
BOMB_RADIUS = 7
BOMB_GRAVITY = 0.55
BLAST = 85               # a bomb knocks out every ball this close
AFTER_LAST_BOMB = 1.2    # seconds the plane stays once its last bomb's gone off
LANDING_HOLD = 1.0       # seconds the pilot's held (safe) once they're back
SPAWN_WEIGHT = {"plane": 0.35}  # how often each kind turns up (1 unless listed)

# How each effect changes the ball (also sent to browsers for prediction)
KINDS = {
    "speed": {"title": "Speed", "seconds": 6, "force": 1.6, "max_speed": 1.35, "gravity": 1.0},
    "float": {"title": "Float", "seconds": 6, "force": 1.0, "max_speed": 1.0, "gravity": 0.45},
    "iron": {"title": "Iron", "seconds": 5, "force": 1.0, "max_speed": 1.0, "gravity": 1.0, "pin_heavy": True},
    "punch": {"title": "Punch", "seconds": 10, "force": 1.0, "max_speed": 1.0, "gravity": 1.0},
    "plane": {"title": "Attack plane", "seconds": PLANE_SECONDS, "force": 1.0, "max_speed": 1.0,
              "gravity": 1.0, "super": True, "bombs": BOMBS, "blast": BLAST, "intro": INTRO_SECONDS},
}
ALL_KINDS = list(KINDS)


def clean_kinds(kinds):
    """The kinds a room asked for, in KINDS order (None: all of them)."""
    if kinds is None:
        return list(ALL_KINDS)
    return [k for k in ALL_KINDS if k in kinds]


class PowerUps:
    def __init__(self, env, rng=None, kinds=None):
        self.env = env
        self.rng = rng or random.Random()
        self.kinds = clean_kinds(kinds) or list(ALL_KINDS)
        # Where the plane flies: along the top, inside any walls and ceiling
        # (Classic's box)
        p = env.players[0]
        self.plane_y = max(PLANE_Y, p.top + 5)
        self.plane_xs = (max(PLANE_MARGIN, p.left + 5), min(env.map.width - PLANE_MARGIN, p.right - 5))
        self.pickups = []                 # [x, y, kind]
        self.effects = [None] * env.n     # per player: [kind, ticks left] or None
        self.collected = [0] * env.n      # pickups each player grabbed (for awards)
        self.reset_round()

    def reset_round(self):
        self.pickups = []
        self.effects = [None] * self.env.n
        self.next_spawn = FIRST_SPAWN * TICK_HZ
        self.pending = None   # who's about to fly (the cutscene's on: see Match)
        self.plane = None     # the plane in the air: see launch()
        self.bombs = []       # falling: [x, y, y speed, pilot]
        self.apply()

    # --- each tick ------------------------------------------------------------
    def apply(self):
        """Set every ball's effect multipliers. Run before each step."""
        for p, eff in zip(self.env.players, self.effects):
            k = KINDS[eff[0]] if eff else None
            p.force_mult = k["force"] if k else 1.0
            p.speed_mult = k["max_speed"] if k else 1.0
            p.gravity_mult = k["gravity"] if k else 1.0
            if k and k.get("pin_heavy"):
                p.m = p.max_m
                p.heavy_held = True  # (so the step ends heavy too: player.end_step)
                p.force_mult *= p.max_m / p.min_m  # heavy, but moves as if it weren't
        if self.plane:
            # The pilot's out of play (held: nothing hits them, they don't move)
            pilot = self.env.players[self.plane["i"]]
            pilot.held = max(pilot.held, 2)

    # --- the attack plane -----------------------------------------------------
    def launch(self):
        """The cutscene's over: the pilot takes off."""
        i, self.pending = self.pending, None
        if i is None:
            return
        p = self.env.players[i]
        self.plane = {"i": i, "x": min(max(p.x, self.plane_xs[0]), self.plane_xs[1]),
                      "dir": 1 if p.x < self.env.map.width / 2 else -1,
                      "ticks": PLANE_SECONDS * TICK_HZ, "bombs": BOMBS, "gap": 0,
                      "from": (p.x, p.y), "done_in": None, "pressed": True}
        p.x_v = p.y_v = 0.0
        self.apply()

    def land(self):
        """The plane's time is up: the pilot is back where they took off."""
        plane, self.plane = self.plane, None
        p = self.env.players[plane["i"]]
        p.x, p.y = plane["from"]
        p.x_v = p.y_v = 0.0
        self.env._inside_walls(p)  # (not where the sudden-death walls have closed in)
        p.held = round(LANDING_HOLD * TICK_HZ)
        return {"e": "land", "i": plane["i"], "x": round(p.x, 1), "y": round(p.y, 1)}

    def _fly(self, buttons):
        """One tick of the plane: steer, drop bombs, bombs fall and go off."""
        env, plane, events = self.env, self.plane, []
        ts = env.time_scale
        b = buttons[plane["i"]] if plane is not None else None
        if plane is not None:
            if b is None:
                b = self._bot_pilot()
            steer = int(bool(b.right)) - int(bool(b.left))
            if steer:
                plane["dir"] = steer
            plane["x"] = min(max(plane["x"] + steer * PLANE_SPEED * ts, self.plane_xs[0]), self.plane_xs[1])
            drop = bool(b.up or b.down or b.heavy)
            plane["gap"] = max(0, plane["gap"] - 1)
            if drop and not plane["pressed"] and plane["bombs"] and not plane["gap"]:
                plane["bombs"] -= 1
                plane["gap"] = round(BOMB_GAP * TICK_HZ)
                self.bombs.append([plane["x"], self.plane_y + 12, 0.0, plane["i"]])
                events.append({"e": "bomb", "i": plane["i"], "x": round(plane["x"], 1)})
            plane["pressed"] = drop  # (a bomb a press, not a stream while it's held)

        for bomb in list(self.bombs):
            bomb[2] += BOMB_GRAVITY * ts
            bomb[1] += bomb[2] * ts
            x, y = bomb[0], bomb[1]
            hit_ball = any(p.alive and not p.held and math.hypot(p.x - x, p.y - y) < p.r + BOMB_RADIUS
                           for p in env.players)
            if y - BOMB_RADIUS > env.map.height:
                self.bombs.remove(bomb)  # (fell out without hitting anything)
            elif hit_ball or env.map.world.solid_at(x, y, BOMB_RADIUS):
                self.bombs.remove(bomb)
                events.append(self._boom(x, y, bomb[3]))

        if plane is not None:
            plane["ticks"] -= 1
            if not plane["bombs"] and not self.bombs and plane["done_in"] is None:
                plane["done_in"] = round(AFTER_LAST_BOMB * TICK_HZ)
            if plane["done_in"] is not None:
                plane["done_in"] -= 1
            if plane["ticks"] <= 0 or (plane["done_in"] is not None and plane["done_in"] <= 0):
                events.append(self.land())
        return events

    def _boom(self, x, y, pilot):
        """A bomb goes off: everyone close enough (but the pilot's team) is
        knocked out at the start of the next step, by the pilot."""
        env = self.env
        victims = []
        for j, p in enumerate(env.players):
            if (p.alive and not p.held and env.teams[j] != env.teams[pilot]
                    and math.hypot(p.x - x, p.y - y) < BLAST + p.r):
                p.doomed = True
                env.last_hit[j] = (pilot, env.steps)
                victims.append(j)
        return {"e": "boom", "i": pilot, "x": round(x, 1), "y": round(y, 1), "hit": victims}

    def _bot_pilot(self):
        """A bot flying the plane: over the nearest ball, then drop."""
        env, plane = self.env, self.plane
        targets = [p for j, p in enumerate(env.players)
                   if p.alive and not p.held and env.teams[j] != env.teams[plane["i"]]]
        if not targets:
            return Buttons()
        t = min(targets, key=lambda p: abs(p.x - plane["x"]))
        dx = t.x - plane["x"]
        close = abs(dx) < 14
        return Buttons(left=dx < -4, right=dx > 4, down=close and not plane["pressed"])

    def step(self, info, buttons=None):
        """After each physics step. Returns events for the browsers.
        buttons: each player's Buttons this step (None for a bot), for
        flying the plane."""
        env = self.env
        events = []
        if info["round_over"]:
            self.reset_round()
            return events
        if self.plane is not None or self.bombs:
            events += self._fly(buttons or [None] * env.n)
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
            if (eff and eff[0] == "punch" and hit is not None and hit[1] == env.steps
                    and env.teams[hit[0]] != env.teams[i]):  # not on a teammate
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
                if p.alive and not p.held and math.hypot(p.x - x, p.y - y) < p.r + PICKUP_RADIUS:
                    if kind == SUPER and (self.plane is not None or self.pending is not None):
                        continue  # (one plane at a time)
                    self.pickups.remove(pickup)
                    self.collected[i] += 1
                    events.append({"e": "pickup", "i": i, "k": kind, "x": round(x, 1), "y": round(y, 1)})
                    if kind == SUPER:
                        self.effects[i] = None
                        self.pending = i
                        events.append({"e": "super", "i": i, "k": kind})
                    else:
                        self.effects[i] = [kind, KINDS[kind]["seconds"] * TICK_HZ]
                    break

        # Spawn
        self.next_spawn -= 1
        if self.next_spawn <= 0:
            self.next_spawn = self.rng.uniform(*SPAWN_GAP) * TICK_HZ
            if len(self.pickups) < MAX_ON_MAP:
                spot = self._spot()
                kind = self._pick_kind() if spot is not None else None
                if kind is not None:
                    self.pickups.append([spot[0], spot[1], kind])
                    events.append({"e": "spawn", "k": kind, "x": round(spot[0], 1), "y": round(spot[1], 1)})
        return events

    def _pick_kind(self):
        """A kind to spawn (the plane rarer, and never two at once)."""
        busy = (self.plane is not None or self.pending is not None
                or any(k == SUPER for _, _, k in self.pickups))
        kinds = [k for k in self.kinds if not (k == SUPER and busy)]
        if not kinds:
            return None
        weights = [SPAWN_WEIGHT.get(k, 1.0) for k in kinds]
        return self.rng.choices(kinds, weights)[0]

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
        out = {
            "pickups": [[round(x, 1), round(y, 1), k] for x, y, k in self.pickups],
            "effects": [None if e is None else [e[0], round(e[1] / TICK_HZ, 1)] for e in self.effects],
        }
        if self.plane is not None:
            pl = self.plane
            # [pilot, x, y, facing (1 right, -1 left), seconds left, bombs left]
            out["plane"] = [pl["i"], round(pl["x"], 1), self.plane_y, pl["dir"],
                            round(pl["ticks"] / TICK_HZ, 1), pl["bombs"]]
        if self.pending is not None:
            out["super"] = [self.pending, SUPER]
        if self.bombs:
            out["bombs"] = [[round(b[0], 1), round(b[1], 1)] for b in self.bombs]
        return out


def describe():
    """Effect constants for the browsers (prediction and labels)."""
    return {k: dict(v) for k, v in KINDS.items()}
