import math

import numpy as np

from bonk_game.envs.utils import arena, stepping
from bonk_game.envs.utils.controls import apply_input
from bonk_game.envs.utils.maps import DEFAULT_MAP, make_map
from bonk_game.envs.utils.player import new_rng
from bonk_game.envs.utils.timer import RoundTimer


class TestEnv():
    """Free-for-all match env for 2-10 players, for playing and watching.

    Create it with one controller per player, e.g.
    TestEnv("user", bot, model, map_name="platform"). The env never calls
    the controllers; they're kept in `self.controllers` for the caller.
    Each step takes one input per player (see step()).

    Scoring depends on the map:
    - Maps that restart the round on a death (the open maps): a player who
      dies is out until the next round. The last ball standing scores and
      a new round starts. If everyone left dies at once, they all score.
    - Maps that respawn the dead player (Classic): the player who last hit
      them in the past few seconds scores. With two players, the other
      player always scores.

    A player who respawns mid-round is held for `respawn_hold` steps
    first, so they can see where they are: frozen in place, ignoring their
    keys, and out of play (nothing hits or kills them, and bots go after
    someone else).

    The first to the winning score (the map's default unless given) wins.

    Rounds have a time limit (the map's round_time unless given; 0 turns it
    off). When it runs out, sudden death walls close in from the sides.

    Agents see an observation with their own state, their nearest living
    opponent's, and the map's extra values: the same shape they were
    trained on, whatever the number of players.
    """

    __test__ = False  # not a pytest test class

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 30}

    # A hit counts towards a kill (on respawn maps) for this many steps
    HIT_CREDIT_STEPS = 90
    # Steps a respawned player is held before they play (2 s)
    RESPAWN_HOLD = 60

    def __init__(self, *controllers, render_mode=None, winning_score=None, map_name=DEFAULT_MAP,
                 round_time=None, colors=None, teams=None, respawn=None, gravity=1.0, seed=None,
                 respawn_hold=None, time_scale=stepping.TIME_SCALE):
        """colors: optional colour index (into theme.PLAYER_COLORS) per player.
        teams: optional team number per player. Teammates aren't opponents:
        agents and bots go after the other team, a round ends when one team
        is left, and bumping a teammate off doesn't count as a knockout.
        respawn: True respawns dead players straight away, even on maps that
        normally restart the round; False restarts the round. None: the
        map's own rule.
        gravity: multiplies the pull of gravity on the players.
        time_scale: how fast the world runs (stepping.TIME_SCALE: below 1 is
        slow motion; 1 is the original speed).
        seed: for where players spawn (the env's own random numbers, `rng`;
        None: drawn once from numpy's global ones).
        respawn_hold: steps a respawned player is held (None: RESPAWN_HOLD;
        0 respawns straight into play)."""
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode
        self.map = make_map(map_name)
        self.winning_score = winning_score or self.map.winning_score
        self.obs_size = self.map.obs_size
        self.timer = RoundTimer(self.map.round_time if round_time is None else round_time,
                                self.map.sudden_death_start)

        self.controllers = list(controllers)
        self.n = len(controllers)
        self.teams = list(range(self.n)) if teams is None else list(teams)
        if len(self.teams) != self.n:
            raise ValueError("need a team for each player")
        self.rounds = self.map.reset_round_on_kill if respawn is None else not respawn
        # Respawn maps restart the clock after each point; a mode can turn that off
        self.timer_resets_on_death = True
        self.respawn_hold = self.RESPAWN_HOLD if respawn_hold is None else respawn_hold
        # A player everyone else goes after instead of the nearest (the crown holder)
        self.focus = None
        self.rng = new_rng(seed)
        self.players = list(self.map.make_players(self.n, colors, rng=self.rng))
        self.time_scale = time_scale
        for p in self.players:
            p.gravity *= gravity
            p.time_scale = time_scale
        self.scores = [0] * self.n
        self.last_hit = [None] * self.n  # (index of who hit them, step) per player
        self.kos = []  # this step's deaths: (victim, who knocked them out or None, walls?)
        self.steps = 0
        # Extra balls that copy a player's inputs: [(owner index, player)]
        # (the Swarm power-up: server/powerups.py adds and removes them).
        # They move and bump like anyone, and a bump from one counts as the
        # owner's, but they aren't players: no score, and they can't win.
        self.copies = []

        self.renderer = arena.Renderer(render_mode, self.metadata["render_fps"],
                                       f"Bonk - {self.map.title}")

    @property
    def p1(self):
        return self.players[0]

    @property
    def p2(self):
        return self.players[1]

    @property
    def quit_requested(self):
        """True once the user has closed the game window."""
        return self.renderer.quit_requested

    def view(self, obs, i):
        """Player i's observation out of the stacked obs from step()/reset()."""
        return obs[i * self.obs_size:(i + 1) * self.obs_size]

    def nearest_opponent(self, i):
        """Index of the closest living opponent (any opponent if none are alive)."""
        me = self.players[i]
        others = [j for j in range(self.n) if self.teams[j] != self.teams[i]] or \
            [j for j in range(self.n) if j != i]
        if self.focus is not None and self.focus in others and self.players[self.focus].alive:
            return self.focus
        living = ([j for j in others if self.players[j].alive and not self.players[j].held]
                  or [j for j in others if self.players[j].alive] or others)
        return min(living, key=lambda j: math.dist((me.x, me.y),
                                                   (self.players[j].x, self.players[j].y)))

    def _get_obs(self):
        """Every player's observation stacked, obs_size each (see view())."""
        own = [p.get_obs() for p in self.players]
        extra = self.map.extra_obs()
        views = []
        for i in range(self.n):
            views += [own[i], own[self.nearest_opponent(i)], extra]
        return np.concatenate(views, axis=0)

    def knocked_out_by(self, victim):
        """Who last hit `victim` in the past few seconds (or None)."""
        hit = self.last_hit[victim]
        if (hit is not None and self.steps - hit[1] <= self.HIT_CREDIT_STEPS
                and self.teams[hit[0]] != self.teams[victim]):
            return hit[0]
        return None

    def _credit(self, victim):
        """Who scores for `victim` dying on a respawn map (or None)."""
        by = self.knocked_out_by(victim)
        if by is not None:
            return by
        if self.n == 2 and self.teams[0] != self.teams[1]:
            return 1 - victim
        return None

    def check_collisions(self):
        """Handle deaths: anyone the level knocked out during the last step
        (map.killed) or the sudden-death walls caught.

        Returns (deaths, points, round_over): deaths is [(index, x, y)] of
        players who died this step, where they died; points is the indexes
        of players who scored.
        """
        alive = [i for i, p in enumerate(self.players) if p.alive]
        for i in alive:
            if self.players[i].held:
                self._inside_walls(self.players[i])  # (the walls keep closing)
        # Held players (just respawned, or out of play for a while) can't die yet
        living = [i for i in alive if not self.players[i].held]
        walled = [i for i in living if self.timer.kills(self.players[i])]
        dead = [i for i in living if self.map.killed(self.players[i]) or i in walled]
        for i in living:
            self.players[i].doomed = False
        deaths = [(i, self.players[i].x, self.players[i].y) for i in dead]
        self.kos = [(i, self.knocked_out_by(i), i in walled) for i in dead]
        points = []

        if self.rounds:
            if dead:
                for i in dead:
                    self.players[i].alive = 0
                # (Held players are still in the round)
                remaining = [i for i in alive if i not in dead]
                # The round is over once only one team (or nobody) is left: they
                # score. If the last ones all go at once, they all score.
                over = len({self.teams[i] for i in remaining}) <= 1
                points = (remaining or dead) if over else []
                for i in points:
                    self.players[i].score += 1
                if over:
                    self.new_round()
                    return deaths, points, True
        else:
            for i in dead:
                scorer = self._credit(i)
                if scorer is not None:
                    points.append(scorer)
                    self.players[scorer].score += 1
            if dead and self.timer_resets_on_death:
                self.timer.reset()
            for i in dead:
                # Respawn away from everyone else
                arena.respawn_apart(self.players[i], [p for j, p in enumerate(self.players) if j != i])
                self._inside_walls(self.players[i])
                self.players[i].held = self.respawn_hold
                self.last_hit[i] = None
        return deaths, points, False

    def _inside_walls(self, p):
        """During sudden death, respawn between the closing walls, not past
        them (where you'd die again straight away)."""
        w = self.timer.walls()
        if w is not None and w[1] - w[0] > 2 * p.r + 2:
            p.x = min(max(p.x, w[0] + p.r + 1), w[1] - p.r - 1)

    def new_round(self):
        self.map.reset()
        self.timer.reset()
        self.map.place_players(self.players)
        self.last_hit = [None] * self.n

    def reset(self):
        for p in self.players:
            p.score = 0
        self.scores = [0] * self.n
        self.steps = 0
        self.new_round()
        if self.render_mode == "human":
            self._render_frame()
        return self._get_obs()

    def step(self, actions=None):
        """Advance one step.

        `actions` has one input per player: a discrete action (0-15), a
        controls.Buttons, or None for no input. Leaving it out means nobody
        presses anything.

        Returns (obs, terminated, info). info has "deaths", "points" and
        "round_over" as returned by check_collisions(), and "kos": for each
        death, (victim, who knocked them out or None, killed by the
        sudden-death walls?).
        """
        actions = [None] * self.n if actions is None else list(actions)
        if len(actions) != self.n:
            raise ValueError(f"expected {self.n} inputs, got {len(actions)}")
        # (Held players were held before this step: they start playing the
        # step after the hold runs out)
        held = [p.held > 0 for p in self.players]
        for p, a, h in zip(self.players, actions, held):
            if p.alive and not h:
                apply_input(p, a)
        for owner, c in self.copies:
            if self.players[owner].alive and not held[owner]:
                apply_input(c, actions[owner])
        self.map.step(move=False)  # (stepping.advance moves everything)
        self.timer.step()
        self.steps += 1
        deaths, points, round_over = self.check_collisions()
        movers = []
        for i, (p, h) in enumerate(zip(self.players, held)):
            if h and p.held:
                p.held -= 1
            elif p.alive and not p.held:
                movers.append(i)

        n_real = len(movers)

        def who(k):
            """(player index, is it a copy?) for a mover index."""
            return (movers[k], False) if k < n_real else (self.copies[k - n_real][0], True)

        def contact(a, b):
            (a, a_copy), (b, b_copy) = who(a), who(b)
            if a == b:
                return
            # (A copy bumping someone is its owner's hit; nobody hit the owner)
            if not a_copy:
                self.last_hit[a] = (b, self.steps)
            if not b_copy:
                self.last_hit[b] = (a, self.steps)

        stepping.advance([self.players[i] for i in movers] + [c for _, c in self.copies], self.map,
                         on_contact=contact, time_scale=self.time_scale)

        self.scores = [p.score for p in self.players]
        terminated = max(self.scores) >= self.winning_score

        if self.render_mode == "human":
            self._render_frame()
            terminated = terminated or self.quit_requested

        info = {"deaths": deaths, "points": points, "round_over": round_over, "kos": self.kos}
        return self._get_obs(), terminated, info

    def render(self):
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def _render_frame(self):
        return self.renderer.draw(self.players, self.map, self.scores, self.timer, self.respawn_hold)

    def close(self):
        self.renderer.close()
