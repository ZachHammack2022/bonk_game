import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

import bonk_game  # noqa: F401  (registers the gym envs)
from bonk_game.envs.utils.maps import DEFAULT_MAP, agent_dir, env_id

BAD_STEPS = 50_000
AGENT_STEPS = 500_000
N_ENVS = 4
AGENT_NAMES = ["ppo", "a2c", "dqn", "ars"]


def make_env(map_name=DEFAULT_MAP):
    from stable_baselines3.common.env_util import make_vec_env
    return make_vec_env(env_id(map_name), n_envs=N_ENVS)


def create_models(env, verbose):
    from stable_baselines3 import PPO, A2C, DQN
    from sb3_contrib import ARS
    return {
        "ppo": PPO("MlpPolicy", env, verbose=verbose),
        "a2c": A2C("MlpPolicy", env, verbose=verbose),
        "dqn": DQN("MlpPolicy", env, verbose=verbose),
        "ars": ARS("LinearPolicy", env, verbose=verbose),
    }


def train_bad_agent(map_name=DEFAULT_MAP, verbose=0, steps=BAD_STEPS):
    """Train the sparring partner that the other agents learn against."""
    from stable_baselines3 import PPO
    print("Training the bad agent.")
    model = PPO("MlpPolicy", make_env(map_name), verbose=verbose)
    model.learn(total_timesteps=steps, progress_bar=True)
    model.save(f"{agent_dir(map_name)}/bad")


def train(models, map_name=DEFAULT_MAP, steps=AGENT_STEPS):
    """Train and save each model.

    Args:
        models (dict): (str) name -> (model object) model
    """
    for key, model in models.items():
        print(f"Training the {key} agent.")
        model.learn(total_timesteps=steps, progress_bar=True)
        model.save(f"{agent_dir(map_name)}/{key}")


def delete_models(names, map_name=DEFAULT_MAP):
    for key in names:
        path = f"{agent_dir(map_name)}/{key}.zip"
        if os.path.exists(path):
            os.remove(path)


def check_agents(map_name=DEFAULT_MAP):
    """True if at least one trained agent already exists for this map."""
    return any(os.path.exists(f"{agent_dir(map_name)}/{key}.zip") for key in AGENT_NAMES)


def train_models(map_name=DEFAULT_MAP, steps=AGENT_STEPS):
    """Train the bad agent, then every agent against it.

    `steps` is per agent; the bad agent gets a tenth of it.
    """
    os.makedirs(agent_dir(map_name), exist_ok=True)

    # Delete old agents from files
    delete_models(["bad"] + AGENT_NAMES, map_name)

    # Train the bad agent first...
    train_bad_agent(map_name, steps=max(1000, steps // 10))

    # ...then build fresh envs. BonkEnv loads ./agents/bad.zip when it's
    # constructed, so these envs must be made *after* the bad agent is saved
    # or every agent would train against an opponent that never moves.
    env = make_env(map_name)
    train(create_models(env, verbose=0), map_name, steps=steps)

    print("All agents have been trained!")
