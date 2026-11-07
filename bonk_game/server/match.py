"""One online match: the game env plus the countdown / round / results flow.

The server calls tick() 30 times a second. Nothing here knows about the
network: humans' inputs come in through set_input(), and snapshot() is
what gets sent to every browser.

The flow mirrors the desktop game (bonk_game/ui/app.py, MatchScene):
countdown (3, 2, 1) -> play -> after a round ends, a short pause and a
2-beat countdown -> ... -> "over" for a moment once someone wins.

Every match has its own random seed, so the same seed and the same inputs
give the same match.
"""
import math
import random

import numpy as np

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils import arena, stepping, world
from bonk_game.envs.utils.controls import NO_BUTTONS, Buttons
from bonk_game.envs.utils.player import POGO
from bonk_game.server import modes, powerups
from bonk_game.server.scene import level_shapes, player_motion, player_state
from bonk_game.ui import theme
from bonk_game.ui.bot import LEVEL_NAMES, Bot

TICK_HZ = 30          # physics steps per second (what the game was tuned for)
BEAT = 0.55           # seconds per countdown number
ROUND_PAUSE = 1.1     # seconds between a round ending and the next countdown
OVER_PAUSE = 1.4      # seconds showing the final point before results

BOT_KINDS = tuple(f"bot:{level}" for level in LEVEL_NAMES)
STAND_IN = "bot:medium"  # plays for a human who drops out mid-match


def bot_level(kind):
    return kind.split(":", 1)[1] if ":" in kind else "medium"


def is_bot(kind):
    return kind == "bot" or kind.startswith("bot:")


class Match:
    def __init__(self, map_name, slots, first_to, agents=None, mode=modes.DEFAULT_MODE,
                 round_time=None, gravity=1.0, power_ups=False, seed=None,
                 speed=stepping.TIME_SCALE, power_kinds=None):
        """slots: one dict per player, {"kind": "human" | "bot:<level>" | agent
        name, "name": display name, "color": optional colour index, "team":
        0 or 1 in the teams mode}. agents: name -> trained model, for any
        agent kinds. first_to: the mode's goal (points, lives, minutes or
        seconds; see modes.py). round_time: seconds before sudden death
        (None: the map's own, 0: off). gravity: a multiplier. speed: how
        fast the world runs (stepping.TIME_SCALE; 1 is the original speed). power_ups:
        turn on pickups (see powerups.py); power_kinds: which ones (None:
        all). seed: for everything random in
        the match (None: pick one)."""
        agents = agents or {}
        # (from numpy's random numbers, so np.random.seed() still makes a
        # repeatable match, as it did before matches had their own)
        self.seed = int(np.random.randint(2 ** 31)) if seed is None else int(seed)
        self.options = {"mode": mode, "first_to": first_to, "round_time": round_time,
                        "gravity": gravity, "speed": speed, "power_ups": bool(power_ups),
                        "power_kinds": powerups.clean_kinds(power_kinds)}
        self.map_name = map_name
        self.slots = [dict(s) for s in slots]
        self.first_to = first_to
        self.gravity = gravity
        kinds = [s["kind"] for s in self.slots]
        self.colors = [s.get("color", i) for i, s in enumerate(self.slots)]
        teams = [s.get("team", k % 2) for k, s in enumerate(self.slots)]
        self.mode = modes.make_mode(mode, len(kinds), first_to, teams, rng=random.Random(self.seed + 1))
        options = {"round_time": round_time, **self.mode.env_options()}
        self.env = TestEnv(*kinds, map_name=map_name, colors=self.colors, gravity=gravity, seed=self.seed,
                           time_scale=speed, **options)
        self.mode.start(self.env)
        self.powerups = (powerups.PowerUps(self.env, random.Random(self.seed + 2), power_kinds)
                         if power_ups else None)
        self.controllers = []
        for i, kind in enumerate(kinds):
            if kind == "human":
                self.controllers.append(None)
            elif is_bot(kind):
                self.controllers.append(Bot(self.env, i, bot_level(kind), rng=random.Random(self.seed + 10 + i)))
            else:
                self.controllers.append(agents[kind])
        self.inputs = [NO_BUTTONS] * len(kinds)
        self.tapped = set()  # slots that pressed a drop button since the last step (see _buttons)
        self.stand_ins = {}  # slot -> Bot playing for a disconnected human
        self.obs = self.env.reset()
        self.done = False       # someone reached first_to
        self.finished = False   # done and the final pause is over
        self.tick_count = 0
        self.stats = [new_stats() for _ in kinds]
        self.set_phase("countdown", 3)

    @property
    def n(self):
        return self.env.n

    def set_phase(self, phase, countdown=0):
        self.phase = phase
        self.phase_t = 0.0
        self.countdown_len = countdown
        self.last_beat = None

    # --- input ------------------------------------------------------------
    def set_input(self, slot, buttons):
        if self.controllers[slot] is None:
            new = buttons if isinstance(buttons, Buttons) else Buttons(*map(bool, buttons))
            old = self.inputs[slot]
            if (new.up and not old.up) or (new.down and not old.down) or (new.heavy and not old.heavy):
                self.tapped.add(slot)
            self.inputs[slot] = new

    def stand_in(self, slot):
        """A Medium bot plays for a human who dropped out."""
        if self.controllers[slot] is None and slot not in self.stand_ins:
            self.stand_ins[slot] = Bot(self.env, slot, bot_level(STAND_IN))
            self.inputs[slot] = NO_BUTTONS

    def can_drop_in(self):
        """Can someone take over a bot's seat now? In modes where balls
        respawn, any time; otherwise between rounds, so nobody appears in
        the middle of one."""
        return not self.done and (self.mode.respawns or self.phase in ("countdown", "scored"))

    def take_seat(self, slot, info):
        """Someone who joined during the match takes over a bot's seat
        (#35). info: their slot dict (name, id, colour, look). They keep the
        bot's score and colour; the stats start again, as they're theirs."""
        self.slots[slot] = {**info, "kind": "human", "color": self.colors[slot],
                            "team": self.slots[slot].get("team")}
        self.controllers[slot] = None
        self.stand_ins.pop(slot, None)
        self.inputs[slot] = NO_BUTTONS
        self.stats[slot] = new_stats()

    def release(self, slot):
        """The human is back: stop the stand-in bot."""
        self.stand_ins.pop(slot, None)
        self.inputs[slot] = NO_BUTTONS

    def _actions(self):
        out = []
        for i, c in enumerate(self.controllers):
            c = self.stand_ins.get(i, c)
            if c is None:
                out.append(self.inputs[i])
            elif self.env.players[i].alive:
                out.append(c.predict(self.env.view(self.obs, i))[0])
            else:
                out.append(None)
        return out

    # --- simulation ---------------------------------------------------------
    def tick(self):
        """Advance 1/30 s. Returns a list of event dicts for the browsers:
        beep, go, death, score, round, sudden, hit, over."""
        self.tick_count += 1
        dt = 1 / TICK_HZ
        self.phase_t += dt
        events = []

        if self.phase == "countdown":
            beat = int(self.phase_t / BEAT)
            if beat != self.last_beat:
                self.last_beat = beat
                events.append({"e": "beep" if beat < self.countdown_len else "go"})
            if self.phase_t >= BEAT * self.countdown_len:
                self.set_phase("play")
            return events

        if self.phase == "scored":
            if self.phase_t >= ROUND_PAUSE:
                self.set_phase("countdown", 2)
            return events

        if self.phase == "super":
            # Everything stands still for the super power-up's cutscene
            if self.phase_t >= powerups.INTRO_SECONDS:
                self.powerups.launch()
                self.set_phase("play")
            return events

        if self.phase == "over":
            if self.phase_t >= OVER_PAUSE:
                self.finished = True
            return events

        return self._step_physics()

    def _step_physics(self):
        env = self.env
        living = [i for i, p in enumerate(env.players) if p.alive]
        pre = {i: (env.players[i].x, env.players[i].y, env.players[i].x_v, env.players[i].y_v)
               for i in living}
        was_sudden = env.timer.sudden_death
        if self.powerups:
            self.powerups.apply()
        actions = self._actions()
        self.obs, _, info = env.step(actions)
        events = self.mode.step(info)
        if self.powerups:
            events += self.powerups.step(info, self._buttons())
        self.done = self.mode.done

        for i in living:
            self.stats[i]["alive"] += 1
        if env.timer.sudden_death and not was_sudden:
            events.append({"e": "sudden"})
        kos = {victim: (by, wall) for victim, by, wall in info["kos"]}
        for i, x, y in info["deaths"]:
            by, wall = kos.get(i, (None, False))
            self.stats[i]["deaths"] += 1
            if by is not None:
                self.stats[by]["kos"] += 1
            elif not wall:
                self.stats[i]["falls"] += 1
            events.append({"e": "death", "i": i, "x": round(x, 1), "y": round(y, 1),
                           "by": by, "wall": wall})
        if info["round_over"]:
            events.append({"e": "round"})
        if not info["deaths"]:
            hits = _hits(env.players, [i for i in living if not env.players[i].held], pre)
            for h in hits:
                st = self.stats[h["by"]]
                st["best_hit"] = max(st["best_hit"], h["s"])
            if hits:
                events.append(max(hits, key=lambda h: h["s"]))

        if self.done:
            self.set_phase("over")
            events.append({"e": "over"})
        elif info["round_over"]:
            self.set_phase("scored")
        elif self.powerups and self.powerups.pending is not None:
            self.set_phase("super")
        return events

    def _buttons(self):
        """What each person is pressing (None for bots and stand-ins). A
        quick tap that was let go before this step still counts as a press
        this step (dropping a bomb from the plane), once."""
        out = []
        for i, c in enumerate(self.controllers):
            b = self.inputs[i] if c is None and i not in self.stand_ins else None
            if b is not None and i in self.tapped:
                b = b._replace(down=True)
            out.append(b)
        self.tapped.clear()
        return out

    # --- what the browsers see ----------------------------------------------
    def countdown_number(self):
        """3, 2, 1 during a countdown ("Ready"/"Set" for the 2-beat one), else None."""
        if self.phase != "countdown":
            return None
        beat = int(self.phase_t / BEAT)
        return self.countdown_len - beat if beat < self.countdown_len else None

    def snapshot(self):
        env = self.env
        timer = env.timer
        return {
            "type": "state",
            "tick": self.tick_count,
            "phase": self.phase,
            "count": self.countdown_number(),
            "count_len": self.countdown_len,
            "players": [player_state(p) for p in env.players],
            "scores": self.mode.scores(),
            "level": level_shapes(env.map),
            **self._parts(),
            "timer": None if not timer.enabled else round(timer.remaining, 1),
            "walls": None if timer.walls() is None else [round(w, 1) for w in timer.walls()],
            "t": round(timer.steps / TICK_HZ, 2),
            "stand_ins": sorted(self.stand_ins),
            **self._held(),
            **self.mode.extra_state(),
            **(self.powerups.state() if self.powerups else {}),
        }

    def _parts(self):
        """{"parts": [x, y, x speed, y speed] of each moving part} (the
        sliding platform, the swing...), for the browser's physics."""
        parts = self.env.map.world.part_states()
        return {"parts": parts} if parts else {}

    def _held(self):
        """{"held": seconds each player has left of their respawn hold (0:
        playing)}, while anyone's held."""
        held = [round(p.held / TICK_HZ, 1) if p.alive and p.held else 0 for p in self.env.players]
        return {"held": held} if any(held) else {}

    def motion(self, i):
        """Player i's speeds, for their own browser only (see room.py)."""
        return player_motion(self.env.players[i])

    def describe(self):
        """Static info about the match, sent once when it starts."""
        return {
            "type": "match",
            "map": self.map_name,
            "title": self.env.map.title,
            "first_to": self.first_to,
            "mode": self.mode.id,
            "mode_title": self.mode.title,
            "goal": self.mode.goal_text(),
            "team_names": list(modes.TEAM_NAMES) if self.mode.id == "teams" else None,
            "team_colors": list(modes.TEAM_HEX) if self.mode.id == "teams" else None,
            "radius": self.env.players[0].r,
            "width": self.env.map.width,
            "height": self.env.map.height,
            "reset_round_on_kill": self.env.rounds,
            "respawn_hold": round(self.env.respawn_hold / TICK_HZ, 2),
            "physics": self.physics(),
            "powerups": powerups.describe() if self.powerups else None,
            "slots": [self.describe_slot(i) for i in range(len(self.slots))],
        }

    def describe_slot(self, i):
        s = self.slots[i]
        return {"name": s["name"], "kind": s["kind"], "id": s.get("id"),
                "team": self.env.teams[i] if self.mode.id == "teams" else None,
                "pattern": s.get("pattern", "plain"),
                "trail": s.get("trail", "none"), "hat": s.get("hat", "none"), "ko": s.get("ko", "pop"),
                "color": s.get("own_color") or theme_color(self.colors[i]),
                "color_name": "Custom" if s.get("own_color") else theme.PLAYER_NAMES[self.colors[i]]}

    def physics(self):
        """What the browser's copy of the physics needs (static/physics.js):
        the ball's settings, the level as Box2D bodies, and Box2D's own."""
        p = self.env.players[0]
        return {
            "force": p.push,  # sideways and down
            "fly_force": arena.FORCE,  # up, on maps where you fly
            "hover": p.hover,  # share of gravity "up" cancels in the air (jump maps)
            "gravity": p.gravity,
            "max_speed": p.v_range,
            "can_fly": p.can_fly,
            "jump_speed": p.jump_speed,
            "pogo": POGO,  # a jump on landing keeps this share of the landing speed
            "min_m": p.min_m,
            "max_m": p.max_m,
            "substeps": stepping.SUBSTEPS,  # Box2D steps per physics step
            # How fast the world runs: scales moves, gravity and pushes
            "time_scale": self.env.time_scale,
            "tick_ms": 1000 / TICK_HZ,
            # Classic never lets you sink below its floor (player.clamp_bottom)
            "clamp_bottom": p.bottom if p.clamp_bottom else None,
            "box2d": {
                "ppm": world.PPM, "step_seconds": world.STEP_SECONDS, "base_gravity": world.GRAVITY,
                "friction_scale": world.FRICTION_SCALE, "grip": world.GRIP,
                "grip_running": world.GRIP_RUNNING, "lift_off": world.LIFT_OFF,
                "player_bounce": world.PLAYER_BOUNCE,
                "velocity_iterations": world.VELOCITY_ITERATIONS,
                "position_iterations": world.POSITION_ITERATIONS,
            },
            "world": self.env.map.world.describe(),
        }

    def results(self):
        res = {"type": "results", "mode": self.mode.id, "map": self.map_name, **self.mode.results(),
               "stats": [dict(st, alive=round(st["alive"] / TICK_HZ, 1),
                              pickups=self.powerups.collected[i] if self.powerups else 0)
                         for i, st in enumerate(self.stats)],
               # In Knockouts, most knockouts is the score already
               "awards": [a for a in awards(self.stats, self.powerups.collected if self.powerups else None)
                          if not (self.mode.id == "knockouts" and a["id"] == "kos")]}
        res["summaries"] = summaries(res, self.mode.teams if self.mode.id == "teams" else None)
        return res


def summaries(res, teams=None):
    """How each player did, for their match history (profiles.py):
    [{place, of, won, score, kos, falls, deaths, best_hit, pickups, awards}].
    place is 1 for the winner, then by score (ties share a place); in Teams
    it's your team's place, 1 for both in a draw."""
    scores, winner = res["scores"], res.get("winner")
    out = []
    for i, st in enumerate(res["stats"]):
        if teams is not None:
            wt = res.get("winner_team")
            won = wt is not None and teams[i] == wt
            place, of = (1 if wt is None or won else 2), 2
        else:
            won = winner == i
            ahead = sum(1 for j, s in enumerate(scores) if j != winner and s > scores[i])
            place = 1 if won else ahead + 1 + (winner is not None)
            of = len(scores)
        out.append({"place": place, "of": of, "won": won, "score": scores[i],
                    "kos": st["kos"], "falls": st["falls"], "deaths": st["deaths"],
                    "best_hit": round(st["best_hit"], 1), "pickups": st.get("pickups", 0),
                    "awards": [a["id"] for a in res["awards"] if i in a["slots"]]})
    return out


def theme_color(i):
    return "#%02x%02x%02x" % theme.PLAYER_COLORS[i]


def new_stats():
    """What happened to one player during a match (for the awards)."""
    # kos: knockouts they made; falls: times they fell out with nobody near;
    # deaths: times they were knocked out or fell; alive: ticks spent alive
    # while playing; best_hit: fastest collision they made (px per tick)
    return {"kos": 0, "falls": 0, "deaths": 0, "alive": 0, "best_hit": 0.0}


def _leaders(stats, key, best=max):
    values = [st[key] for st in stats]
    top = best(values)
    return [i for i, v in enumerate(values) if v == top], top


def awards(stats, pickups=None):
    """A few fun titles for the results screen. Each is
    {"id", "title", "slots": [winner slots], "value"}; one is left out when
    nobody earned it (no knockouts, no falls) or everyone tied."""
    out = []

    def give(id_, title, key, best=max, keep=lambda v: v > 0):
        slots, value = _leaders(stats, key, best)
        if keep(value) and len(slots) < len(stats):
            out.append({"id": id_, "title": title, "slots": slots, "value": value})

    give("kos", "Most knockouts", "kos")
    give("hit", "Hardest hit", "best_hit")
    give("falls", "Butterfingers", "falls")
    if pickups is not None:
        stats = [dict(st, pickups=n) for st, n in zip(stats, pickups)]
        give("pickups", "Power hungry", "pickups")
    # Survivor: knocked out the fewest times, ties broken by time alive
    order = sorted(range(len(stats)), key=lambda i: (stats[i]["deaths"], -stats[i]["alive"]))
    a, b = stats[order[0]], stats[order[1]] if len(order) > 1 else None
    if b is not None and (a["deaths"], a["alive"]) != (b["deaths"], b["alive"]):
        out.append({"id": "survivor", "title": "Survivor", "slots": [order[0]],
                    "value": a["deaths"]})
    for award in out:
        if award["id"] == "hit":
            award["value"] = round(award["value"], 1)
    return out


def _hits(players, living, pre):
    """Players who bumped into each other this step, hard enough to count:
    [{"e": "hit", x, y, "s": closing speed, "by": the faster one}]."""
    out = []
    for k, i in enumerate(living):
        for j in living[k + 1:]:
            p, q = players[i], players[j]
            if not (p.alive and q.alive) or math.hypot(p.x - q.x, p.y - q.y) > p.r + q.r + 1.5:
                continue
            x1, y1, vx1, vy1 = pre[i]
            x2, y2, vx2, vy2 = pre[j]
            dx, dy = x2 - x1, y2 - y1
            dd = math.hypot(dx, dy) or 1
            towards_q = (vx1 * dx + vy1 * dy) / dd   # i's speed towards j
            towards_p = -(vx2 * dx + vy2 * dy) / dd  # j's speed towards i
            closing = towards_q + towards_p
            if closing > 5:
                out.append({"e": "hit", "x": round((p.x + q.x) / 2, 1), "y": round((p.y + q.y) / 2, 1),
                            "s": round(closing, 1), "by": i if towards_q >= towards_p else j})
    return out
