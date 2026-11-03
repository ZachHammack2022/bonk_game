import os

import gym
import numpy as np

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.mechanics import env_collision_gym, player_collision

BAD_AGENT_PATH = "./agents/bad"


class BonkEnv(gym.Env):
    """Single-agent training env.

    The learning agent controls player 1. Player 2 is controlled by the
    "bad" agent from ./agents/bad.zip if it exists, otherwise it just falls
    under gravity. An episode ends as soon as either player hits a wall.
    """

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 60}

    def __init__(self, render_mode=None, opponent_path=BAD_AGENT_PATH):
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode

        self.p1, self.p2 = arena.make_players()
        self.players = [self.p1, self.p2]
        self.env_objects = arena.make_platforms()

        self.observation_space = gym.spaces.Box(-1, 1, shape=(arena.OBS_SIZE,), dtype=np.float64)
        self.action_space = gym.spaces.Discrete(arena.N_ACTIONS)

        # Load the opponent if it has been trained. Imported lazily so the
        # env (and its physics) can be used without stable-baselines3.
        self.bad_agent = None
        if opponent_path and os.path.exists(f"{opponent_path}.zip"):
            from stable_baselines3 import PPO
            self.bad_agent = PPO.load(opponent_path)

        self.renderer = arena.Renderer(render_mode, self.metadata["render_fps"], "Bonk Training")

    def _get_obs(self, bad_agent=False):
        """Observation from player 1's view, or player 2's if bad_agent."""
        me, them = (self.p2, self.p1) if bad_agent else (self.p1, self.p2)
        return np.concatenate((me.get_obs(), them.get_obs()), axis=0)

    def seed(self, seed=None):
        # Players spawn using numpy's global RNG
        np.random.seed(seed)
        return [seed]

    def check_collisions(self):
        for env_obj in self.env_objects:
            for p in self.players:
                env_collision_gym(p, env_obj)
        player_collision(self.p1, self.p2)

    def reset(self, seed=None, options=None):
        if seed is not None:
            self.seed(seed)
        arena.reset_players(self.players)
        if self.render_mode == "human":
            self._render_frame()
        return self._get_obs()

    def step(self, action):
        # Opponent acts on the current state, seen from its own side
        if self.bad_agent is not None:
            action2, _states = self.bad_agent.predict(self._get_obs(bad_agent=True))
            arena.apply_action(self.p2, action2)

        arena.apply_action(self.p1, action)

        self.check_collisions()
        self.p1.update()
        self.p2.update()

        # An episode is done if agent or enemy dies
        terminated = not (self.p1.alive and self.p2.alive)
        reward = -0.001  # small time penalty to encourage finishing fights
        if terminated:
            # Sparse win/loss reward. If both die on the same step, it's a draw.
            reward = float(self.p1.alive) - float(self.p2.alive)

        if self.render_mode == "human":
            self._render_frame()

        return self._get_obs(), reward, terminated, {}

    def render(self, mode=None):
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def _render_frame(self):
        return self.renderer.draw(self.players, self.env_objects)

    def close(self):
        self.renderer.close()
