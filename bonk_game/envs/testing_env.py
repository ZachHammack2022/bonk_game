import itertools
import math
import os

import numpy as np

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.maps import DEFAULT_MAP, make_map
from bonk_game.envs.utils.mechanics import player_collision
from bonk_game.envs.utils.timer import RoundTimer

# (up, left, down, right, heavy) keys for each human player; any key in a
# group works. Caps Lock isn't used: on macOS it reads as held while toggled.
P1_KEYS = ((pygame.K_w,), (pygame.K_a,), (pygame.K_s,), (pygame.K_d,), (pygame.K_LSHIFT,))
P2_KEYS = ((pygame.K_UP,), (pygame.K_LEFT,), (pygame.K_DOWN,), (pygame.K_RIGHT,),
           (pygame.K_RSHIFT, pygame.K_SPACE))
P3_KEYS = ((pygame.K_i,), (pygame.K_j,), (pygame.K_k,), (pygame.K_l,), (pygame.K_h,))
P4_KEYS = ((pygame.K_KP8,), (pygame.K_KP4,), (pygame.K_KP5, pygame.K_KP2), (pygame.K_KP6,),
           (pygame.K_KP0,))
PLAYER_KEYS = (P1_KEYS, P2_KEYS, P3_KEYS, P4_KEYS)

# On maps where players respawn, a death scores for whoever last touched the
# victim within this many steps (4 s). With two players it's always the other.
CREDIT_STEPS = 120


class TestEnv():
    """The game's env: 2-4 players for playing and watching matches.

    Each player is either a trained model or the string "user" for keyboard
    control. Pass players 3 and 4 in `more`.

    - On maps that restart the round on a death, a player who dies is out
      until the round ends, and the last one standing scores. (If everyone
      left dies at once, they each score.) With two players this is simply
      "a death scores for the other player".
    - On maps that respawn players (Classic), the dead player respawns and
      whoever last touched them scores.

    The first to the winning score (the map's default unless given) wins.
    Rounds have a time limit (the map's round_time unless given; 0 turns it
    off). When it runs out, sudden death walls close in from the sides.
    """

    __test__ = False  # not a pytest test class

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 30}

    def __init__(self, model1, model2, render_mode=None, winning_score=None, map_name=DEFAULT_MAP,
                 round_time=None, more=()):
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        kinds = [model1, model2, *more]
        if not 2 <= len(kinds) <= arena.MAX_PLAYERS:
            raise ValueError(f"2 to {arena.MAX_PLAYERS} players, got {len(kinds)}")
        self.render_mode = render_mode
        self.map = make_map(map_name)
        self.winning_score = winning_score or self.map.winning_score
        self.obs_size = self.map.obs_size
        self.timer = RoundTimer(self.map.round_time if round_time is None else round_time,
                                self.map.sudden_death_start)

        self.n = len(kinds)
        self.users = [k == "user" for k in kinds]
        self.models = [None if u else k for u, k in zip(self.users, kinds)]
        self.user1, self.user2 = self.users[:2]
        self.model1, self.model2 = self.models[:2]

        self.players = list(self.map.make_players(self.n))
        self.p1, self.p2 = self.players[:2]
        self.scores = [0] * self.n
        self.out = [False] * self.n  # knocked out for the rest of the round
        self.last_touch = [None] * self.n  # (who, step) that last touched each player
        self.steps = 0
        self.events = []  # what happened on the last step, for the game to show

        self.renderer = arena.Renderer(render_mode, self.metadata["render_fps"],
                                       f"Bonk - {self.map.title}")

    @property
    def quit_requested(self):
        """True once the user has closed the game window."""
        return self.renderer.quit_requested

    def active(self):
        """Indices of the players still in this round."""
        return [i for i in range(self.n) if not self.out[i]]

    def opponent_of(self, i):
        """The opponent player i watches: the nearest one still in the round."""
        me = self.players[i]
        others = [j for j in self.active() if j != i] or [j for j in range(self.n) if j != i]
        j = min(others, key=lambda j: math.dist((me.x, me.y), (self.players[j].x, self.players[j].y)))
        return self.players[j]

    def _get_obs(self):
        """Every player's observation, stacked: [p1 view, p2 view, ...].

        Each view is obs_size long: [me, opponent, map extras], where the
        opponent is the nearest player still in the round. Slice player i's
        with obs[i * env.obs_size:(i + 1) * env.obs_size].
        """
        extra = self.map.extra_obs()
        views = []
        for i, p in enumerate(self.players):
            views += [p.get_obs(), self.opponent_of(i).get_obs(), extra]
        return np.concatenate(views, axis=0)

    def credit(self, victim):
        """Who scores for a death on a respawn map (None for nobody)."""
        if self.n == 2:
            return 1 - victim
        touch = self.last_touch[victim]
        if touch is not None and self.steps - touch[1] <= CREDIT_STEPS:
            return touch[0]
        return None

    def check_collisions(self):
        P = self.players
        died = [i for i in self.active() if self.map.collide(P[i]) or self.timer.kills(P[i])]
        for i in died:
            self.events.append(("death", i, (P[i].x, P[i].y)))

        if died and self.map.reset_round_on_kill:
            for i in died:
                self.out[i] = True
                P[i].alive = 0
            alive = self.active()
            if len(alive) <= 1:
                # Last one standing takes the round; if everyone left died
                # at once, they each get the point.
                for i in alive or died:
                    P[i].score += 1
                    self.events.append(("point", i))
                self.events.append(("round_over",))
                self.new_round()
                return
        elif died:
            for i in died:
                scorer = self.credit(i)
                if scorer is not None:
                    P[scorer].score += 1
                    self.events.append(("point", scorer))
            self.timer.reset()
            for i in died:
                arena.respawn_apart(P[i], [P[j] for j in range(self.n) if j != i])
                self.last_touch[i] = None

        for a, b in itertools.combinations(self.active(), 2):
            pa, pb = P[a], P[b]
            if math.hypot(pa.x - pb.x, pa.y - pb.y) < pa.r + pb.r:
                self.last_touch[a] = (b, self.steps)
                self.last_touch[b] = (a, self.steps)
            player_collision(pa, pb)

    def new_round(self):
        self.map.reset()
        self.timer.reset()
        self.out = [False] * self.n
        self.last_touch = [None] * self.n
        arena.reset_players(self.players)

    def check_keydown(self, keys, agent):
        idx = self.players.index(agent)
        up, left, down, right, heavy = PLAYER_KEYS[idx]

        def held(group):
            return any(keys[k] for k in group)

        if held(up):
            agent.move_up(arena.FORCE)
        if held(left):
            agent.move_left(arena.FORCE)
        if held(down):
            agent.move_down(arena.FORCE)
        if held(right):
            agent.move_right(arena.FORCE)
        if held(heavy):
            agent.make_heavy()

    def apply_forces(self, actions):
        """Apply this step's inputs.

        `actions` holds one action per model-controlled player, in player
        order. With exactly one model it's that model's action on its own
        (not in a list). Keyboard players read the keys.
        """
        keys = pygame.key.get_pressed() if any(self.users) else None
        model_idx = [i for i in range(self.n) if not self.users[i]]
        acts = [actions] if len(model_idx) == 1 else list(actions) if model_idx else []
        for i, p in enumerate(self.players):
            if self.out[i]:
                continue
            if self.users[i]:
                self.check_keydown(keys, p)
            else:
                arena.apply_action(p, acts[model_idx.index(i)])

    def reset(self):
        for p in self.players:
            p.score = 0
        self.scores = [0] * self.n
        self.steps = 0
        self.new_round()
        if self.render_mode == "human":
            self._render_frame()
        return self._get_obs()

    def step(self, actions):
        self.events = []
        self.apply_forces(actions)
        self.map.step()
        self.timer.step()
        self.check_collisions()
        for i, p in enumerate(self.players):
            if not self.out[i]:
                p.update()
        self.steps += 1

        self.scores = [p.score for p in self.players]
        terminated = max(self.scores) >= self.winning_score

        if self.render_mode == "human":
            self._render_frame()
            terminated = terminated or self.quit_requested

        return self._get_obs(), terminated, {}

    def render(self):
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def _render_frame(self):
        shown = [p for i, p in enumerate(self.players) if not self.out[i]]
        return self.renderer.draw(shown, self.map, self.scores, self.timer)

    def close(self):
        self.renderer.close()
