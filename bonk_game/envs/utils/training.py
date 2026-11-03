import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

import bonk_game  # noqa: F401  (registers the gym env)
from bonk_game.envs.utils.testing import AGENT_DIR

BAD_STEPS = 50_000
AGENT_STEPS = 500_000
N_ENVS = 4
AGENT_NAMES = ["ppo", "a2c", "dqn", "ars"]


def make_env():
    from stable_baselines3.common.env_util import make_vec_env
    return make_vec_env("bonk_game/bonk-v0", n_envs=N_ENVS)


def create_models(env, verbose):
    from stable_baselines3 import PPO, A2C, DQN
    from sb3_contrib import ARS
    return {
        "ppo": PPO("MlpPolicy", env, verbose=verbose),
        "a2c": A2C("MlpPolicy", env, verbose=verbose),
        "dqn": DQN("MlpPolicy", env, verbose=verbose),
        "ars": ARS("LinearPolicy", env, verbose=verbose),
    }


def train_bad_agent(verbose=0):
    """Train the sparring partner that the other agents learn against."""
    from stable_baselines3 import PPO
    print("Training the bad agent.")
    model = PPO("MlpPolicy", make_env(), verbose=verbose)
    model.learn(total_timesteps=BAD_STEPS, progress_bar=True)
    model.save(f"{AGENT_DIR}/bad")


def train(models):
    """Train and save each model.

    Args:
        models (dict): (str) name -> (model object) model
    """
    for key, model in models.items():
        print(f"Training the {key} agent.")
        model.learn(total_timesteps=AGENT_STEPS, progress_bar=True)
        model.save(f"{AGENT_DIR}/{key}")


def delete_models(names):
    for key in names:
        path = f"{AGENT_DIR}/{key}.zip"
        if os.path.exists(path):
            os.remove(path)


def check_agents():
    """True if at least one trained agent already exists."""
    return any(os.path.exists(f"{AGENT_DIR}/{key}.zip") for key in AGENT_NAMES)


def train_models():
    os.makedirs(AGENT_DIR, exist_ok=True)

    # Delete old agents from files
    delete_models(["bad"] + AGENT_NAMES)

    # Train the bad agent first...
    train_bad_agent()

    # ...then build fresh envs. BonkEnv loads ./agents/bad.zip when it's
    # constructed, so these envs must be made *after* the bad agent is saved
    # or every agent would train against an opponent that never moves.
    env = make_env()
    train(create_models(env, verbose=0))

    print("All agents have been trained!")
