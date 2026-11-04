import os

import gymnasium as gym
import numpy as np

from bonk_game.envs.utils import arena, stepping
from bonk_game.envs.utils.maps import DEFAULT_MAP, agent_dir, make_map
from bonk_game.envs.utils.mechanics import player_collision


class BonkEnv(gym.Env):
    """Single-agent training env.

    The learning agent controls player 1. Player 2 is the opponent:

    - with `opponents` (an OpponentPool), a new opponent is picked from the
      pool at every reset: the built-in Bot, the bad agent, or a snapshot
      of the learner itself;
    - otherwise the map's "bad" agent (e.g. ./agents/bad.zip) if it exists,
      or nobody (player 2 is just left to physics).

    An episode ends as soon as either player dies.
    """

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 60}

    def __init__(self, render_mode=None, map_name=DEFAULT_MAP, opponent_path="default", opponents=None):
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode

        self.map = make_map(map_name)
        self.p1, self.p2 = self.map.make_players()
        self.players = [self.p1, self.p2]

        self.observation_space = gym.spaces.Box(-1, 1, shape=(self.map.obs_size,), dtype=np.float64)
        self.action_space = gym.spaces.Discrete(arena.N_ACTIONS)

        # Load the opponent if it has been trained. Imported lazily so the
        # env (and its physics) can be used without stable-baselines3.
        if opponent_path == "default":
            opponent_path = f"{agent_dir(map_name)}/bad"
        self.opponents = opponents
        self.bad_agent = None
        if opponents is None and opponent_path and os.path.exists(f"{opponent_path}.zip"):
            from stable_baselines3 import PPO
            self.bad_agent = PPO.load(opponent_path)
        self.opponent = self.bad_agent

        self.renderer = arena.Renderer(render_mode, self.metadata["render_fps"],
                                       f"Bonk Training - {self.map.title}")

    def _get_obs(self, bad_agent=False):
        """Observation from player 1's view, or player 2's if bad_agent."""
        me, them = (self.p2, self.p1) if bad_agent else (self.p1, self.p2)
        return np.concatenate((me.get_obs(), them.get_obs(), self.map.extra_obs()), axis=0)


    def check_collisions(self):
        for p in self.players:
            if self.map.collide(p) or p.doomed:
                p.dies()
        player_collision(self.p1, self.p2)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        # Players spawn using the env's own random numbers (seeded by reset)
        for p in self.players:
            p.rng = self.np_random
        self.map.reset()
        arena.reset_players(self.players)
        if self.opponents is not None:
            self.opponent = self.opponents.sample(self, index=1)
        if self.render_mode == "human":
            self._render_frame()
        return self._get_obs(), {}

    def step(self, action):
        # Opponent acts on the current state, seen from its own side
        if self.opponent is not None:
            action2, _states = self.opponent.predict(self._get_obs(bad_agent=True))
            arena.apply_action(self.p2, action2)

        arena.apply_action(self.p1, action)

        self.map.step(move=False)  # (stepping.advance moves its parts)
        self.check_collisions()
        stepping.advance(self.players, self.map)

        # An episode is done if agent or enemy dies
        terminated = not (self.p1.alive and self.p2.alive)
        reward = -0.001  # small time penalty to encourage finishing fights
        if terminated:
            # Sparse win/loss reward. If both die on the same step, it's a draw.
            reward = float(self.p1.alive) - float(self.p2.alive)

        if self.render_mode == "human":
            self._render_frame()

        # Time limits (truncation) come from the TimeLimit wrapper that
        # gymnasium.make adds, using max_episode_steps from registration.
        return self._get_obs(), reward, terminated, False, {}

    def render(self):
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def _render_frame(self):
        return self.renderer.draw(self.players, self.map)

    def close(self):
        self.renderer.close()
