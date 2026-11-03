"""Check every map's training env against stable-baselines3's env checker.

Run with: python -m bonk_game.envs.check_env
"""
import gymnasium as gym
from stable_baselines3.common.env_checker import check_env

import bonk_game  # noqa: F401  (registers the envs)
from bonk_game.envs.utils.maps import MAPS, env_id

if __name__ == "__main__":
    for name in MAPS:
        check_env(gym.make(env_id(name)).unwrapped)
        print(f"{env_id(name)}: ok")
