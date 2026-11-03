import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

import bonk_game  # noqa: F401  (registers the gym envs)
from bonk_game.envs.utils.maps import DEFAULT_MAP, agent_dir, env_id

BAD_STEPS = 50_000
AGENT_STEPS = 500_000
N_ENVS = 4
AGENT_NAMES = ["ppo", "a2c", "dqn", "ars"]


SNAPSHOT_EVERY = 25_000  # self-play: add a copy of the learner to its pool this often


def make_env(map_name=DEFAULT_MAP, pool=None):
    """Vectorized training envs. With a pool, opponents are sampled from it;
    without one, envs use the map's bad agent (the old behaviour)."""
    from stable_baselines3.common.env_util import make_vec_env
    kwargs = {} if pool is None else {"opponents": pool}
    return make_vec_env(env_id(map_name), n_envs=N_ENVS, env_kwargs=kwargs)


def model_class(name):
    from stable_baselines3 import PPO, A2C, DQN
    from sb3_contrib import ARS
    return {"bad": PPO, "ppo": PPO, "a2c": A2C, "dqn": DQN, "ars": ARS}[name]


def create_model(name, env, verbose=0):
    policy = "LinearPolicy" if name == "ars" else "MlpPolicy"
    return model_class(name)(policy, env, verbose=verbose)


def train_bad_agent(map_name=DEFAULT_MAP, verbose=0, steps=BAD_STEPS):
    """Train the sparring partner, against the built-in Bot."""
    from bonk_game.envs.utils.opponents import OpponentPool
    print("Training the bad agent.")
    pool = OpponentPool(map_name, weights={"bot": 1.0}, load_bad=False)
    model = create_model("bad", make_env(map_name, pool), verbose)
    model.learn(total_timesteps=steps, progress_bar=True)
    model.save(f"{agent_dir(map_name)}/bad")


def train_agent(name, map_name=DEFAULT_MAP, steps=AGENT_STEPS, opponents="mix", verbose=0):
    """Train one agent and save it.

    opponents: "mix" samples a new opponent each episode from the Bot, the
    bad agent and snapshots of this agent (self-play); "bad" trains against
    the bad agent only.
    """
    from bonk_game.envs.utils.opponents import OpponentPool, snapshot_callback
    print(f"Training the {name} agent.")
    callback = None
    if opponents == "mix":
        pool = OpponentPool(map_name)
        env = make_env(map_name, pool)
        folder = os.path.join(agent_dir(map_name), "selfplay", name)
        callback = snapshot_callback(pool, model_class(name), min(SNAPSHOT_EVERY, max(500, steps // 4)), folder)
    else:
        env = make_env(map_name)
    model = create_model(name, env, verbose)
    model.learn(total_timesteps=steps, progress_bar=True, callback=callback)
    model.save(f"{agent_dir(map_name)}/{name}")
    return model


def delete_models(names, map_name=DEFAULT_MAP):
    for key in names:
        path = f"{agent_dir(map_name)}/{key}.zip"
        if os.path.exists(path):
            os.remove(path)


def check_agents(map_name=DEFAULT_MAP):
    """True if at least one trained agent already exists for this map."""
    return any(os.path.exists(f"{agent_dir(map_name)}/{key}.zip") for key in AGENT_NAMES)


def train_models(map_name=DEFAULT_MAP, steps=AGENT_STEPS, opponents="mix"):
    """Train the bad agent, then every other agent.

    `steps` is per agent; the bad agent gets a tenth of it. See train_agent
    for `opponents`.
    """
    os.makedirs(agent_dir(map_name), exist_ok=True)

    # Delete old agents from files
    delete_models(["bad"] + AGENT_NAMES, map_name)

    # Train the bad agent first...
    train_bad_agent(map_name, steps=max(1000, steps // 10))

    # ...then the rest. Envs are built per agent, after bad.zip is saved,
    # so they can load it.
    for name in AGENT_NAMES:
        train_agent(name, map_name, steps, opponents)

    print("All agents have been trained!")
