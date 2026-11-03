import os

import numpy as np

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.maps import DEFAULT_MAP, make_map
from bonk_game.envs.utils.mechanics import player_collision

# (up, left, down, right, heavy) keys for each human player
P1_KEYS = (pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_CAPSLOCK)
P2_KEYS = (pygame.K_UP, pygame.K_LEFT, pygame.K_DOWN, pygame.K_RIGHT, pygame.K_SPACE)


class TestEnv():
    """Two-player env for playing/watching matches.

    Each player is either a trained model or the string "user" for keyboard
    control. When a player dies the opponent scores; depending on the map
    either the dead player respawns or the whole round restarts. The first
    to the winning score (the map's default unless given) wins.
    """

    __test__ = False  # not a pytest test class

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 30}

    def __init__(self, model1, model2, render_mode=None, winning_score=None, map_name=DEFAULT_MAP):
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode
        self.map = make_map(map_name)
        self.winning_score = winning_score or self.map.winning_score
        self.obs_size = self.map.obs_size

        self.user1 = model1 == "user"
        self.user2 = model2 == "user"
        self.model1 = None if self.user1 else model1
        self.model2 = None if self.user2 else model2

        self.p1, self.p2 = self.map.make_players()
        self.players = [self.p1, self.p2]
        self.scores = [0, 0]

        self.renderer = arena.Renderer(render_mode, self.metadata["render_fps"],
                                       f"Bonk - {self.map.title}")

    @property
    def quit_requested(self):
        """True once the user has closed the game window."""
        return self.renderer.quit_requested

    def _get_obs(self):
        """Both players' observations stacked: [p1 view, p2 view].

        Each view is obs_size long; slice with obs[:env.obs_size] and
        obs[env.obs_size:].
        """
        p1, p2 = self.p1.get_obs(), self.p2.get_obs()
        extra = self.map.extra_obs()
        return np.concatenate((p1, p2, extra, p2, p1, extra), axis=0)

    def check_collisions(self):
        died1, died2 = self.map.collide(self.p1), self.map.collide(self.p2)
        if died1:
            self.p2.score += 1
        if died2:
            self.p1.score += 1

        if self.map.reset_round_on_kill:
            # Last one standing takes the round (both dying at once is a
            # double point); then everything restarts.
            if died1 or died2:
                self.new_round()
                return
        else:
            # Respawn just the dead player, away from the opponent
            if died1:
                arena.respawn_apart(self.p1, [self.p2])
            if died2:
                arena.respawn_apart(self.p2, [self.p1])
        player_collision(self.p1, self.p2)

    def new_round(self):
        self.map.reset()
        arena.reset_players(self.players)

    def check_keydown(self, keys, agent):
        up, left, down, right, heavy = P2_KEYS if agent is self.p2 else P1_KEYS
        if keys[up]:
            agent.move_up(arena.FORCE)
        if keys[left]:
            agent.move_left(arena.FORCE)
        if keys[down]:
            agent.move_down(arena.FORCE)
        if keys[right]:
            agent.move_right(arena.FORCE)
        if keys[heavy]:
            agent.make_heavy()

    def apply_forces(self, actions):
        """Apply this step's inputs.

        `actions` is [action1, action2] when both players are models, a single
        action when exactly one is a model, and ignored when both are users.
        """
        keys = pygame.key.get_pressed() if (self.user1 or self.user2) else None

        if self.user1:
            self.check_keydown(keys, self.p1)
        else:
            arena.apply_action(self.p1, actions if self.user2 else actions[0])

        if self.user2:
            self.check_keydown(keys, self.p2)
        else:
            arena.apply_action(self.p2, actions if self.user1 else actions[1])

    def reset(self):
        for p in self.players:
            p.score = 0
        self.scores = [0, 0]
        self.new_round()
        if self.render_mode == "human":
            self._render_frame()
        return self._get_obs()

    def step(self, actions):
        self.apply_forces(actions)
        self.map.step()
        self.check_collisions()
        self.p1.update()
        self.p2.update()

        self.scores = [self.p1.score, self.p2.score]
        terminated = max(self.scores) >= self.winning_score

        if self.render_mode == "human":
            self._render_frame()
            terminated = terminated or self.quit_requested

        return self._get_obs(), terminated, {}

    def render(self):
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def _render_frame(self):
        return self.renderer.draw(self.players, self.map, self.scores)

    def close(self):
        self.renderer.close()
