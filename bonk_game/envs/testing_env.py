import math

import numpy as np

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.controls import apply_input
from bonk_game.envs.utils.maps import DEFAULT_MAP, make_map
from bonk_game.envs.utils.mechanics import player_collision
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

    def __init__(self, *controllers, render_mode=None, winning_score=None, map_name=DEFAULT_MAP,
                 round_time=None):
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode
        self.map = make_map(map_name)
        self.winning_score = winning_score or self.map.winning_score
        self.obs_size = self.map.obs_size
        self.timer = RoundTimer(self.map.round_time if round_time is None else round_time,
                                self.map.sudden_death_start)

        self.controllers = list(controllers)
        self.n = len(controllers)
        self.players = list(self.map.make_players(self.n))
        self.scores = [0] * self.n
        self.last_hit = [None] * self.n  # (index of who hit them, step) per player
        self.steps = 0

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
        others = [j for j in range(self.n) if j != i]
        living = [j for j in others if self.players[j].alive] or others
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

    def _credit(self, victim):
        """Who scores for `victim` dying on a respawn map (or None)."""
        hit = self.last_hit[victim]
        if hit is not None and self.steps - hit[1] <= self.HIT_CREDIT_STEPS:
            return hit[0]
        if self.n == 2:
            return 1 - victim
        return None

    def check_collisions(self):
        """Collide players with the level and each other, and handle deaths.

        Returns (deaths, points, round_over): deaths is [(index, x, y)] of
        players who died this step, where they died; points is the indexes
        of players who scored.
        """
        living = [i for i, p in enumerate(self.players) if p.alive]
        dead = [i for i in living
                if self.map.collide(self.players[i]) or self.timer.kills(self.players[i])]
        deaths = [(i, self.players[i].x, self.players[i].y) for i in dead]
        points = []

        if self.map.reset_round_on_kill:
            if dead:
                for i in dead:
                    self.players[i].alive = 0
                remaining = [i for i in living if i not in dead]
                points = remaining if len(remaining) == 1 else [] if remaining else dead
                for i in points:
                    self.players[i].score += 1
                if len(remaining) <= 1:
                    self.new_round()
                    return deaths, points, True
        else:
            for i in dead:
                scorer = self._credit(i)
                if scorer is not None:
                    points.append(scorer)
                    self.players[scorer].score += 1
            if dead:
                self.timer.reset()
            for i in dead:
                # Respawn away from everyone else
                arena.respawn_apart(self.players[i], [p for j, p in enumerate(self.players) if j != i])
                self.last_hit[i] = None
        self._collide_players()
        return deaths, points, False

    def _collide_players(self):
        living = [i for i, p in enumerate(self.players) if p.alive]
        for k, i in enumerate(living):
            for j in living[k + 1:]:
                a, b = self.players[i], self.players[j]
                if math.hypot(a.x - b.x, a.y - b.y) < a.r + b.r:
                    self.last_hit[i] = (j, self.steps)
                    self.last_hit[j] = (i, self.steps)
                    player_collision(a, b)

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
        "round_over" as returned by check_collisions().
        """
        actions = [None] * self.n if actions is None else list(actions)
        if len(actions) != self.n:
            raise ValueError(f"expected {self.n} inputs, got {len(actions)}")
        for p, a in zip(self.players, actions):
            if p.alive:
                apply_input(p, a)
        self.map.step()
        self.timer.step()
        self.steps += 1
        deaths, points, round_over = self.check_collisions()
        for p in self.players:
            if p.alive:
                p.update()

        self.scores = [p.score for p in self.players]
        terminated = max(self.scores) >= self.winning_score

        if self.render_mode == "human":
            self._render_frame()
            terminated = terminated or self.quit_requested

        info = {"deaths": deaths, "points": points, "round_over": round_over}
        return self._get_obs(), terminated, info

    def render(self):
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def _render_frame(self):
        return self.renderer.draw(self.players, self.map, self.scores, self.timer)

    def close(self):
        self.renderer.close()
