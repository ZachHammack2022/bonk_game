"""One online match: the game env plus the countdown / round / results flow.

The server calls tick() 30 times a second. Nothing here knows about the
network: humans' inputs come in through set_input(), and snapshot() is
what gets sent to every browser.

The flow mirrors the desktop game (bonk_game/ui/app.py, MatchScene):
countdown (3, 2, 1) -> play -> after a round ends, a short pause and a
2-beat countdown -> ... -> "over" for a moment once someone wins.
"""
import math

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils import arena
from bonk_game.envs.utils.mechanics import BOUNCE
from bonk_game.envs.utils.controls import NO_BUTTONS, Buttons
from bonk_game.server.scene import level_shapes, player_state
from bonk_game.ui import theme
from bonk_game.ui.bot import LEVEL_NAMES, Bot

TICK_HZ = 30          # physics steps per second (what the game was tuned for)
BEAT = 0.55           # seconds per countdown number
ROUND_PAUSE = 1.1     # seconds between a round ending and the next countdown
OVER_PAUSE = 1.4      # seconds showing the final point before results

BOT_KINDS = tuple(f"bot:{level}" for level in LEVEL_NAMES)
STAND_IN = "bot:medium"  # plays for a human who drops out mid-match
GRAVITY = 1.5      # player.update_velocities
MASS_DECAY = 0.1   # player.update_mass


def bot_level(kind):
    return kind.split(":", 1)[1] if ":" in kind else "medium"


def is_bot(kind):
    return kind == "bot" or kind.startswith("bot:")


class Match:
    def __init__(self, map_name, slots, first_to, agents=None):
        """slots: one dict per player, {"kind": "human" | "bot:<level>" | agent
        name, "name": display name, "color": optional colour index}. agents:
        name -> trained model, for any agent kinds."""
        agents = agents or {}
        self.map_name = map_name
        self.slots = [dict(s) for s in slots]
        self.first_to = first_to
        kinds = [s["kind"] for s in self.slots]
        self.colors = [s.get("color", i) for i, s in enumerate(self.slots)]
        self.env = TestEnv(*kinds, winning_score=first_to, map_name=map_name, colors=self.colors)
        self.controllers = []
        for i, kind in enumerate(kinds):
            if kind == "human":
                self.controllers.append(None)
            elif is_bot(kind):
                self.controllers.append(Bot(self.env, i, bot_level(kind)))
            else:
                self.controllers.append(agents[kind])
        self.inputs = [NO_BUTTONS] * len(kinds)
        self.stand_ins = {}  # slot -> Bot playing for a disconnected human
        self.obs = self.env.reset()
        self.done = False       # someone reached first_to
        self.finished = False   # done and the final pause is over
        self.tick_count = 0
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
            self.inputs[slot] = buttons if isinstance(buttons, Buttons) else Buttons(*map(bool, buttons))

    def stand_in(self, slot):
        """A Medium bot plays for a human who dropped out."""
        if self.controllers[slot] is None and slot not in self.stand_ins:
            self.stand_ins[slot] = Bot(self.env, slot, bot_level(STAND_IN))
            self.inputs[slot] = NO_BUTTONS

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

        if self.phase == "over":
            if self.phase_t >= OVER_PAUSE:
                self.finished = True
            return events

        return self._step_physics()

    def _step_physics(self):
        env = self.env
        living = [p for p in env.players if p.alive]
        pre = {id(p): (p.x, p.y, p.x_v, p.y_v) for p in living}
        was_sudden = env.timer.sudden_death
        self.obs, self.done, info = env.step(self._actions())

        events = []
        if env.timer.sudden_death and not was_sudden:
            events.append({"e": "sudden"})
        for i, x, y in info["deaths"]:
            events.append({"e": "death", "i": i, "x": round(x, 1), "y": round(y, 1)})
        for i in info["points"]:
            events.append({"e": "score", "i": i})
        if info["round_over"]:
            events.append({"e": "round"})
        if not info["deaths"]:
            hit = _hardest_hit(living, pre)
            if hit:
                events.append(hit)

        if self.done:
            self.set_phase("over")
            events.append({"e": "over"})
        elif info["round_over"]:
            self.set_phase("scored")
        return events

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
            "scores": list(env.scores),
            "level": level_shapes(env.map),
            "timer": None if not timer.enabled else round(timer.remaining, 1),
            "walls": None if timer.walls() is None else [round(w, 1) for w in timer.walls()],
            "t": round(timer.steps / TICK_HZ, 2),
            "stand_ins": sorted(self.stand_ins),
        }

    def describe(self):
        """Static info about the match, sent once when it starts."""
        return {
            "type": "match",
            "map": self.map_name,
            "title": self.env.map.title,
            "first_to": self.first_to,
            "radius": self.env.players[0].r,
            "width": self.env.map.width,
            "height": self.env.map.height,
            "reset_round_on_kill": self.env.map.reset_round_on_kill,
            "physics": self.physics(),
            "slots": [
                {"name": s["name"], "kind": s["kind"], "id": s.get("id"),
                 "color": theme_color(self.colors[i]), "color_name": theme.PLAYER_NAMES[self.colors[i]]}
                for i, s in enumerate(self.slots)
            ],
        }

    def physics(self):
        """Constants the client needs to predict its own ball (predict.js)."""
        p = self.env.players[0]
        return {
            "force": arena.FORCE,
            "gravity": GRAVITY,
            "max_speed": p.v_range,
            "can_fly": p.can_fly,
            "jump_speed": p.jump_speed,
            "min_m": p.min_m,
            "max_m": p.max_m,
            "mass_decay": MASS_DECAY,
            # Bounce off surfaces that don't say (Classic's floor and ceiling)
            "bounce": abs(BOUNCE) if p.can_fly else 0.3,
            "tick_ms": 1000 / TICK_HZ,
            # Classic never lets you sink below its floor (player.clamp_bottom)
            "clamp_bottom": p.bottom if p.clamp_bottom else None,
        }

    def results(self):
        scores = list(self.env.scores)
        best = max(scores)
        winner = scores.index(best) if scores.count(best) == 1 else None
        return {"type": "results", "scores": scores, "winner": winner}


def theme_color(i):
    return "#%02x%02x%02x" % theme.PLAYER_COLORS[i]


def _hardest_hit(living, pre):
    best = None
    for k, p in enumerate(living):
        for q in living[k + 1:]:
            if math.hypot(p.x - q.x, p.y - q.y) > p.r + q.r + 1.5:
                continue
            x1, y1, vx1, vy1 = pre[id(p)]
            x2, y2, vx2, vy2 = pre[id(q)]
            dd = math.hypot(x2 - x1, y2 - y1) or 1
            closing = ((vx1 - vx2) * (x2 - x1) + (vy1 - vy2) * (y2 - y1)) / dd
            if closing > 5 and (best is None or closing > best["s"]):
                best = {"e": "hit", "x": round((p.x + q.x) / 2, 1), "y": round((p.y + q.y) / 2, 1),
                        "s": round(closing, 1)}
    return best
