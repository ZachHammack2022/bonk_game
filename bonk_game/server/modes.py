"""Game modes for online matches: how you score and when a match ends.

The env (bonk_game/envs/testing_env.py) does the physics and says who
died and who knocked them out. A mode turns that into scores:

- ffa:       free-for-all, as in the desktop game. First to N points.
- teams:     two teams. On round maps the last team standing scores; on
             respawn maps every knockout scores for the other team.
             First team to N points.
- lives:     everyone has N lives and respawns until they run out. Last
             ball with lives left wins. The sudden-death walls still close
             in when the round clock runs out.
- knockouts: N minutes, respawning; most knockouts wins. A tie at the end
             goes to overtime: the next knockout wins.
- crown:     one player wears the crown and gains a point a second while
             they have it. Bump the wearer to steal it; knock them out
             and it's yours. First to hold it N seconds in total wins.

Each mode's `goal` is the one number the host picks (points, lives,
minutes or seconds).
"""
import random

TICK_HZ = 30
NO_LIMIT = 10 ** 9  # a winning score the env never reaches (the mode decides)

# Teams use warm and cool colours, so you can tell sides apart at a glance
# (indexes into theme.PLAYER_COLORS)
TEAM_COLORS = ([0, 4, 2, 6, 9], [1, 7, 3, 5, 8])
TEAM_NAMES = ("Red team", "Blue team")
TEAM_HEX = ("#ef5350", "#4fa3ff")
TEAM_SIZE = len(TEAM_COLORS[0])

CROWN_COOLDOWN = 1.0  # seconds before a crown that just changed hands can move again


class Mode:
    rng = random  # the match gives each mode its own (so replays come out the same)
    id = "base"
    title = ""
    description = ""
    goal_label = "First to"
    goal_choices = (1, 2, 3, 5, 7, 10, 15, 25, 50, 100)
    goal_default = 5
    uses_round_time = True  # the room's round-time setting means something here
    respawns = False        # players respawn mid-round (needs a map with respawn_ok)

    def __init__(self, n, goal, teams=None):
        self.n = n
        self.goal = goal
        self.teams = teams
        self.done = False

    def env_options(self):
        """Extra TestEnv keyword arguments."""
        return {"winning_score": NO_LIMIT}

    def start(self, env):
        self.env = env

    def step(self, info):
        """After each physics step. Returns events for the browsers."""
        return []

    def scores(self):
        raise NotImplementedError

    def winner(self):
        """Winning slot, or None for a draw."""
        scores = self.scores()
        best = max(scores)
        return scores.index(best) if scores.count(best) == 1 else None

    def goal_text(self):
        return f"first to {self.goal}"

    def extra_state(self):
        """Extra fields for each state message."""
        return {}

    def results(self):
        return {"scores": self.scores(), "winner": self.winner()}


class FreeForAll(Mode):
    id = "ffa"
    title = "Free-for-all"
    description = "Everyone for themselves. Score by being the last ball standing (or knocking people out on Classic)."

    def env_options(self):
        return {"winning_score": self.goal}

    def step(self, info):
        if max(self.env.scores) >= self.goal:
            self.done = True
        return [{"e": "score", "i": i} for i in info["points"]]

    def scores(self):
        return list(self.env.scores)


class Teams(Mode):
    id = "teams"
    title = "Teams"
    description = "Red team against Blue team. Last team standing scores the round."

    def __init__(self, n, goal, teams):
        super().__init__(n, goal, teams)
        self.team_scores = [0, 0]

    def env_options(self):
        return {"winning_score": NO_LIMIT, "teams": self.teams}

    def _point(self, team, events):
        self.team_scores[team] += 1
        events.append({"e": "score", "team": team})
        if self.team_scores[team] >= self.goal:
            self.done = True

    def step(self, info):
        events = []
        if self.env.rounds:
            if info["round_over"]:
                won = {self.teams[i] for i in info["points"]}
                if len(won) == 1:
                    self._point(won.pop(), events)
        else:
            for victim, _by, _ in info["kos"]:
                # Knocked out by the other side, or fell: a point for the other side
                self._point(1 - self.teams[victim], events)
        return events

    def scores(self):
        return [self.team_scores[t] for t in self.teams]

    def winning_team(self):
        a, b = self.team_scores
        return None if a == b else (0 if a > b else 1)

    def winner(self):
        return None  # a team wins, not a player

    def extra_state(self):
        return {"team_scores": list(self.team_scores)}

    def results(self):
        return {"scores": self.scores(), "winner": None, "team_scores": list(self.team_scores),
                "winner_team": self.winning_team()}


class Lives(Mode):
    id = "lives"
    title = "Lives"
    description = "Everyone has a few lives and respawns until they run out. Last ball left wins."
    respawns = True
    goal_label = "Lives"
    goal_choices = (1, 2, 3, 5, 7, 10)
    goal_default = 3

    def __init__(self, n, goal, teams=None):
        super().__init__(n, goal)
        self.lives = [goal] * n
        self.last_out = []  # who ran out of lives most recently (for a draw)

    def env_options(self):
        return {"winning_score": NO_LIMIT, "respawn": True}

    def start(self, env):
        super().start(env)
        env.timer_resets_on_death = False

    def step(self, info):
        events = []
        out = []
        for victim, _, _ in info["kos"]:
            self.lives[victim] = max(0, self.lives[victim] - 1)
            if self.lives[victim] == 0:
                self.env.players[victim].alive = 0
                out.append(victim)
                events.append({"e": "eliminated", "i": victim})
        if out:
            self.last_out = out
        if sum(1 for v in self.lives if v > 0) <= 1:
            self.done = True
        return events

    def scores(self):
        return list(self.lives)

    def winner(self):
        left = [i for i, v in enumerate(self.lives) if v > 0]
        return left[0] if len(left) == 1 else None

    def goal_text(self):
        return f"{self.goal} li{'fe' if self.goal == 1 else 'ves'} each"


class Knockouts(Mode):
    id = "knockouts"
    title = "Knockouts"
    description = "Keep respawning. Most knockouts when time runs out wins."
    respawns = True
    goal_label = "Minutes"
    goal_choices = (1, 2, 3, 5)
    goal_default = 2
    uses_round_time = False

    def __init__(self, n, goal, teams=None):
        super().__init__(n, goal)
        self.kos = [0] * n
        self.ticks = 0
        self.overtime = False

    def env_options(self):
        return {"winning_score": NO_LIMIT, "respawn": True, "round_time": 0}

    def step(self, info):
        events = []
        self.ticks += 1
        for _, by, _ in info["kos"]:
            if by is not None:
                self.kos[by] += 1
                events.append({"e": "score", "i": by})
        if self.ticks >= self.goal * 60 * TICK_HZ:
            if self.winner() is not None:
                self.done = True
            elif not self.overtime:
                self.overtime = True
                events.append({"e": "overtime"})
        return events

    def scores(self):
        return list(self.kos)

    def goal_text(self):
        return f"{self.goal} minute{'' if self.goal == 1 else 's'}"

    def clock(self):
        return max(0.0, self.goal * 60 - self.ticks / TICK_HZ)

    def extra_state(self):
        return {"clock": round(self.clock(), 1), "overtime": self.overtime}


class Crown(Mode):
    id = "crown"
    title = "Crown"
    description = "Wear the crown to score. Bump the wearer to steal it."
    respawns = True
    goal_label = "Hold for (s)"
    goal_choices = (15, 20, 30, 45, 60, 90)
    goal_default = 30
    uses_round_time = False

    def __init__(self, n, goal, teams=None, rng=None):
        super().__init__(n, goal)
        self.rng = rng or random
        self.held = [0] * n  # ticks each player has worn the crown
        self.holder = self.rng.randrange(n)
        self.moved_at = -CROWN_COOLDOWN * TICK_HZ
        self.ticks = 0

    def env_options(self):
        return {"winning_score": NO_LIMIT, "respawn": True, "round_time": 0}

    def start(self, env):
        super().start(env)
        env.focus = self.holder

    def _give(self, to, events):
        events.append({"e": "crown", "i": to, "from": self.holder})
        self.holder = to
        self.moved_at = self.ticks
        self.env.focus = to

    def step(self, info):
        env = self.env
        events = []
        self.ticks += 1
        ready = self.ticks - self.moved_at >= CROWN_COOLDOWN * TICK_HZ
        died = {victim: by for victim, by, _ in info["kos"]}
        if self.holder in died:
            # Knocked out: the crown goes to whoever did it, or to whoever
            # has worn it least (a little help for the player behind)
            by = died[self.holder]
            if by is None:
                others = [i for i in range(self.n) if i != self.holder]
                by = min(others, key=lambda i: (self.held[i], self.rng.random()))
            self._give(by, events)
        elif ready:
            hit = env.last_hit[self.holder]
            if hit is not None and hit[1] == env.steps:
                self._give(hit[0], events)
        if env.players[self.holder].alive:
            self.held[self.holder] += 1
        if self.held[self.holder] >= self.goal * TICK_HZ:
            self.done = True
        return events

    def scores(self):
        return [h // TICK_HZ for h in self.held]

    def winner(self):
        return self.holder if self.done else super().winner()

    def goal_text(self):
        return f"hold the crown {self.goal} s"

    def extra_state(self):
        return {"crown": self.holder}


MODES = {m.id: m for m in (FreeForAll, Teams, Lives, Knockouts, Crown)}
DEFAULT_MODE = "ffa"


def make_mode(mode_id, n, goal, teams=None, rng=None):
    """rng: the match's own random numbers (so replays come out the same)."""
    cls = MODES[mode_id]
    if cls is Teams:
        m = cls(n, goal, teams)
    elif cls is Crown:
        m = cls(n, goal, rng=rng)
    else:
        m = cls(n, goal)
    if rng is not None:
        m.rng = rng
    return m


def describe_modes():
    """For the lobby: every mode's name, text and goal choices."""
    return [{"id": m.id, "title": m.title, "description": m.description,
             "goal_label": m.goal_label, "goal_choices": list(m.goal_choices),
             "goal_default": m.goal_default, "round_time": m.uses_round_time,
             "respawns": m.respawns}
            for m in MODES.values()]
