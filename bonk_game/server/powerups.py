"""Power-ups for online matches (a room setting, off by default).

Every few seconds a pickup appears somewhere players can spawn (at most
MAX_ON_MAP at once). Touch it to get its effect for a few seconds:

- speed: you push harder and your top speed goes up
- float: gravity pulls you much less (higher jumps, slower falls)
- iron:  you're as heavy as a heavy ball the whole time, but move as if
         you weren't
- punch: the next player you bump goes flying
- swap:  you trade places (and speeds) with a random opponent, at once
- ghost: you pass through other balls (but not the level)

And the supers: rarer, one at a time. The match freezes for a cutscene
(INTRO_SECONDS) while everyone watches what you got, then:

- plane: you fly along the top of the map for PLANE_SECONDS, out of play
         (nothing can hit you), steering left and right and dropping BOMBS
         bombs. A bomb goes off when it hits a ball or the level, knocking
         out everyone (but your team) within BLAST. Then you're back where
         you were.
- hole:  you turn into a black hole. For HOLE_WARNING you're only
         changing (so everyone sees it coming); then for HOLE_SECONDS
         everyone else is pulled towards you, and anyone who touches you
         is knocked out. You move as usual.
- giant: you're GIANT_SIZE times as big, and as much heavier as you are
         bigger, for a while (you still move as fast).
- swarm: SWARM_COPIES copies of you join in for a while. They do what
         you do; they bump people (that counts as you) and can fall off
         without it costing you anything. Only your own ball can be
         knocked out.

The room picks which of these can turn up (`kinds`). You hold one effect
at a time; a new pickup replaces the old one. Being knocked out ends it.
Pickups (and effects, and a plane) are cleared between rounds.
"""
import copy
import math
import random

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.controls import Buttons
from bonk_game.server.scene import player_state

TICK_HZ = 30
SPAWN_GAP = (5.0, 9.0)   # seconds between new pickups (random in this range)
FIRST_SPAWN = 3.0        # seconds into a round before the first one
MAX_ON_MAP = 2
PICKUP_RADIUS = 11       # size of a pickup (touch distance is this plus the ball's radius)
PUNCH_SPEED = 16         # speed a punched player is sent off at

# Supers (times in seconds, distances in px, speeds in px a physics step,
# like the balls')
INTRO_SECONDS = 2.4      # the match stands still for the cutscene
SUPER_WEIGHT = 0.25      # how often each super turns up, next to 1 for the others
# The attack plane
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
# The black hole
HOLE_WARNING = 1.2       # seconds you're turning into one before it pulls (time to run)
HOLE_SECONDS = 6
HOLE_PULL = 1.2          # speed it adds each step, towards you, within HOLE_NEAR
HOLE_NEAR = 60           # further away, the pull falls off (with the distance squared)
HOLE_CORE = 4            # a ball this close to touching you is out
# Giant, swarm
GIANT_SIZE = 2.0
SWARM_COPIES = 3
SWARM_SPACING = 48       # how far apart the copies start

# How each effect changes the ball (also sent to browsers for prediction)
KINDS = {
    "speed": {"title": "Speed", "seconds": 6, "force": 1.6, "max_speed": 1.35, "gravity": 1.0},
    "float": {"title": "Float", "seconds": 6, "force": 1.0, "max_speed": 1.0, "gravity": 0.45},
    "iron": {"title": "Iron", "seconds": 5, "force": 1.0, "max_speed": 1.0, "gravity": 1.0, "pin_heavy": True},
    "punch": {"title": "Punch", "seconds": 10, "force": 1.0, "max_speed": 1.0, "gravity": 1.0},
    "swap": {"title": "Swap", "seconds": 0, "force": 1.0, "max_speed": 1.0, "gravity": 1.0},
    "ghost": {"title": "Ghost", "seconds": 5, "force": 1.0, "max_speed": 1.0, "gravity": 1.0, "ghost": True},
    "plane": {"title": "Attack plane", "seconds": PLANE_SECONDS, "force": 1.0, "max_speed": 1.0,
              "gravity": 1.0, "super": True, "bombs": BOMBS, "blast": BLAST},
    "hole": {"title": "Black hole", "seconds": HOLE_SECONDS, "force": 1.0, "max_speed": 1.0,
             "gravity": 1.0, "super": True, "core": HOLE_CORE, "warning": HOLE_WARNING},
    "giant": {"title": "Giant", "seconds": 8, "force": 1.0, "max_speed": 0.9, "gravity": 1.0,
              "super": True, "size": GIANT_SIZE},
    "swarm": {"title": "Swarm", "seconds": 10, "force": 1.0, "max_speed": 1.0, "gravity": 1.0,
              "super": True, "copies": SWARM_COPIES},
}
SUPERS = [k for k, v in KINDS.items() if v.get("super")]
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
        self.duds = [0] * env.n           # bombs each player dropped that hit nobody (a badge)
        self.reset_round()

    def reset_round(self):
        self.pickups = []
        self.effects = [None] * self.env.n
        self.next_spawn = FIRST_SPAWN * TICK_HZ
        self.pending = None   # (player, super) about to happen: the cutscene's on (see Match)
        self.plane = None     # the plane in the air: see launch()
        self.bombs = []       # falling: [x, y, y speed, pilot]
        self.super_kos = {}   # victim -> who a bomb or black hole is knocking them out for
        self.hole = None      # the black hole: see launch()
        self.clear_copies()
        self.apply()

    # --- each tick ------------------------------------------------------------
    def apply(self):
        """Set every ball's effects. Run before each step."""
        for i, (p, eff) in enumerate(zip(self.env.players, self.effects)):
            k = KINDS[eff[0]] if eff else None
            p.force_mult = k["force"] if k else 1.0
            p.speed_mult = k["max_speed"] if k else 1.0
            p.gravity_mult = k["gravity"] if k else 1.0
            if k and k.get("pin_heavy"):
                p.m = p.max_m
                p.heavy_held = True  # (so the step ends heavy too: player.end_step)
                p.force_mult *= p.max_m / p.min_m  # heavy, but moves as if it weren't
            p.ghost = bool(k and k.get("ghost"))
            p.r = p.base_r * (k["size"] if k and k.get("size") else 1)
            # A swarm's copies never bump into you, or each other
            p.group = -(i + 1) if any(o == i for o, _ in self.env.copies) else 0
        for o, c in self.env.copies:
            c.force_mult, c.speed_mult, c.gravity_mult = 1.0, 1.0, 1.0
            c.ghost, c.r, c.group = False, c.base_r, -(o + 1)
        if self.plane:
            # The pilot's out of play (held: nothing hits them, they don't move)
            pilot = self.env.players[self.plane["i"]]
            pilot.held = max(pilot.held, 2)
        if self.hole:
            # Nobody can shove a black hole: they're swallowed instead (_hole_step)
            if not self.hole["wait"]:
                self.env.players[self.hole["i"]].ghost = True
            self._pull()

    # --- supers --------------------------------------------------------------
    def super_on(self, i):
        """Is player i's super power on: flying the plane (or its bombs still
        falling), a black hole, a giant or a swarm?"""
        return ((self.plane is not None and self.plane["i"] == i)
                or any(b[3] == i for b in self.bombs)
                or (self.hole is not None and self.hole["i"] == i)
                or bool(self.effects[i] and self.effects[i][0] in SUPERS))

    def busy(self):
        """Is a super on (or about to be)? Only one at a time."""
        return (self.pending is not None or self.plane is not None or self.hole is not None
                or any(e and e[0] in SUPERS for e in self.effects))

    def launch(self):
        """The cutscene's over: the super starts."""
        if self.pending is None:
            return
        (i, kind), self.pending = self.pending, None
        p = self.env.players[i]
        if kind == "plane":
            self._take_off(i, p)
        elif kind == "hole":
            self._open_hole(i)
        else:
            self.effects[i] = [kind, KINDS[kind]["seconds"] * TICK_HZ]
            if kind == "swarm":
                self._make_copies(i)
        self.apply()

    # --- the attack plane -----------------------------------------------------
    def _take_off(self, i, p):
        self.plane = {"i": i, "x": min(max(p.x, self.plane_xs[0]), self.plane_xs[1]),
                      "dir": 1 if p.x < self.env.map.width / 2 else -1,
                      "ticks": PLANE_SECONDS * TICK_HZ, "bombs": BOMBS, "gap": 0,
                      "from": (p.x, p.y), "done_in": None, "pressed": True}
        p.x_v = p.y_v = 0.0

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
                self.duds[bomb[3]] += 1
            elif hit_ball or env.map.world.solid_at(x, y, BOMB_RADIUS):
                self.bombs.remove(bomb)
                boom = self._boom(x, y, bomb[3])
                if not boom["hit"]:
                    self.duds[bomb[3]] += 1
                events.append(boom)

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
                self.super_kos[j] = pilot
                victims.append(j)
        for o, c in env.copies:
            if env.teams[o] != env.teams[pilot] and math.hypot(c.x - x, c.y - y) < BLAST + c.r:
                c.doomed = True  # (pops: _copies_step)
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

    # --- the black hole ---------------------------------------------------------
    # You are the black hole: it's wherever your ball is, and you move as
    # usual. Everyone else is pulled towards you, and touching you knocks
    # them out.
    def _open_hole(self, i):
        self.hole = {"i": i, "wait": round(HOLE_WARNING * TICK_HZ), "ticks": HOLE_SECONDS * TICK_HZ}

    def _hole_at(self):
        p = self.env.players[self.hole["i"]]
        return p.x, p.y

    def _hole_safe(self, j):
        """Is player j safe from the hole? (Its owner and their team are.)"""
        return self.env.teams[j] == self.env.teams[self.hole["i"]]

    def _pull(self):
        """Everyone else (copies too) gets pulled towards the hole."""
        env, h = self.env, self.hole
        if h["wait"]:
            return  # (still turning into one)
        hx, hy = self._hole_at()
        balls = [p for j, p in enumerate(env.players) if not self._hole_safe(j)]
        balls += [c for o, c in env.copies if not self._hole_safe(o)]
        for p in balls:
            if not p.alive or p.held:
                continue
            dx, dy = hx - p.x, hy - p.y
            d = math.hypot(dx, dy) or 1
            dv = HOLE_PULL * min(1.0, (HOLE_NEAR / d) ** 2) * env.time_scale
            p.x_v += dx / d * dv
            p.y_v += dy / d * dv

    def _hole_step(self):
        env, h, events = self.env, self.hole, []
        owner = env.players[h["i"]]
        hx, hy = self._hole_at()
        if not owner.alive:
            self.hole = None  # (knocked out: it's over)
            return events
        if h["wait"]:
            h["wait"] -= 1  # (still turning into one: nothing happens yet)
            if not h["wait"]:
                events.append({"e": "hole_on", "i": h["i"], "x": round(hx, 1), "y": round(hy, 1)})
            return events
        reach = owner.r + HOLE_CORE  # (touching you, or nearly)
        for j, p in enumerate(env.players):
            if (p.alive and not p.held and not self._hole_safe(j)
                    and math.hypot(p.x - hx, p.y - hy) < reach + p.r):
                p.doomed = True  # (out at the start of the next step, to you)
                env.last_hit[j] = (h["i"], env.steps)
                self.super_kos[j] = h["i"]
                events.append({"e": "gulp", "i": h["i"], "j": j, "x": round(p.x, 1), "y": round(p.y, 1)})
        for o, c in env.copies:
            if not self._hole_safe(o) and math.hypot(c.x - hx, c.y - hy) < reach + c.r:
                c.doomed = True
        h["ticks"] -= 1
        if h["ticks"] <= 0:
            self.hole = None
            events.append({"e": "hole_end", "i": h["i"], "x": round(hx, 1), "y": round(hy, 1)})
        return events

    # --- swarm ---------------------------------------------------------------------
    def _make_copies(self, i):
        """Copies of player i, either side of them (where there's ground,
        if there's a choice)."""
        env, p = self.env, self.env.players[i]
        lo, hi = env.map.safe_x_range()
        offsets = [k * SWARM_SPACING for k in (-1, 1, -2, 2, -3, 3, -4, 4)]
        good = [d for d in offsets if lo + p.r < p.x + d < hi - p.r]
        picks = (good + [d for d in offsets if d not in good])[:SWARM_COPIES]
        for d in picks:
            c = copy.copy(p)
            c.x, c.y = p.x + d, p.y - 4
            c.held, c.doomed, c.heavy_held = 0, False, False
            env.copies.append((i, c))

    def clear_copies(self, owner=None):
        """Take away the copies (everyone's, or owner's)."""
        env = self.env
        keep = []
        for o, c in env.copies:
            if owner is None or o == owner:
                env.map.world.drop(c)
            else:
                keep.append((o, c))
        env.copies = keep

    def _copies_step(self):
        """Copies that fell out or touched something deadly pop; and they all
        go when the swarm's over."""
        env, events = self.env, []
        for o, c in list(env.copies):
            eff = self.effects[o]
            ended = not (eff and eff[0] == "swarm") or not env.players[o].alive
            if ended or env.map.killed(c) or env.timer.kills(c):
                env.copies.remove((o, c))
                env.map.world.drop(c)
                events.append({"e": "pop", "i": o, "x": round(c.x, 1), "y": round(c.y, 1), "end": ended})
        return events

    # --- swap -------------------------------------------------------------------------
    def _swap(self, i):
        """Player i trades places (and speeds) with a random opponent."""
        env = self.env
        others = [j for j, q in enumerate(env.players)
                  if q.alive and not q.held and env.teams[j] != env.teams[i]]
        if not others:
            return None
        j = self.rng.choice(others)
        a, b = env.players[i], env.players[j]
        was = (a.x, a.y, b.x, b.y)
        (a.x, a.y, a.x_v, a.y_v), (b.x, b.y, b.x_v, b.y_v) = (b.x, b.y, b.x_v, b.y_v), (a.x, a.y, a.x_v, a.y_v)
        env.last_hit[j] = (i, env.steps)  # (sent somewhere bad: that's on them)
        return {"e": "swap", "i": i, "j": j, "a": [round(was[0], 1), round(was[1], 1)],
                "b": [round(was[2], 1), round(was[3], 1)]}

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
        if self.hole is not None:
            events += self._hole_step()
        for victim, _, _ in info["kos"]:
            self.effects[victim] = None

        # Effects run out
        for i, eff in enumerate(self.effects):
            if eff:
                eff[1] -= 1
                if eff[1] <= 0:
                    self.effects[i] = None
        if env.copies:
            events += self._copies_step()

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
                    if kind in SUPERS and self.busy():
                        continue  # (one super at a time)
                    self.pickups.remove(pickup)
                    self.collected[i] += 1
                    events.append({"e": "pickup", "i": i, "k": kind, "x": round(x, 1), "y": round(y, 1)})
                    if kind in SUPERS:
                        self.effects[i] = None
                        self.pending = (i, kind)
                        events.append({"e": "super", "i": i, "k": kind})
                    elif kind == "swap":
                        swap = self._swap(i)
                        if swap:
                            events.append(swap)
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
        """A kind to spawn (supers rarer, and only one around at once)."""
        busy = self.busy() or any(k in SUPERS for _, _, k in self.pickups)
        kinds = [k for k in self.kinds if not (k in SUPERS and busy)]
        if not kinds:
            return None
        weights = [SUPER_WEIGHT if k in SUPERS else 1.0 for k in kinds]
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
            out["super"] = list(self.pending)
        if self.bombs:
            out["bombs"] = [[round(b[0], 1), round(b[1], 1)] for b in self.bombs]
        if self.hole is not None:
            h = self.hole
            # Everything the browser needs to predict the pull on your ball
            hx, hy = self._hole_at()
            out["hole"] = {"i": h["i"], "x": round(hx, 1), "y": round(hy, 1),
                           "t": round(h["ticks"] / TICK_HZ, 1), "pull": HOLE_PULL, "near": HOLE_NEAR,
                           # seconds before it starts pulling (exact, for the browser's prediction)
                           "w": round(h["wait"] / TICK_HZ, 3),
                           "safe": [j for j in range(self.env.n) if self._hole_safe(j)]}
        if self.env.copies:
            # [owner, x, y, how heavy 0-1]
            out["copies"] = [[o, *player_state(c)[:3]] for o, c in self.env.copies]
        players = self.env.players
        if any(p.r != p.base_r for p in players):
            out["sizes"] = [round(p.r, 1) for p in players]
        return out


def describe():
    """Effect constants for the browsers (prediction and labels)."""
    return {k: {**v, "intro": INTRO_SECONDS} if v.get("super") else dict(v) for k, v in KINDS.items()}
