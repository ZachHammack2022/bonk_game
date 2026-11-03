import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils.maps import DEFAULT_MAP, MAPS, agent_dir


def model_classes():
    """Name -> stable-baselines class used to load each saved agent."""
    from stable_baselines3 import PPO, A2C, DQN
    from sb3_contrib import ARS
    return {
        "bad": PPO,
        "ppo": PPO,
        "a2c": A2C,
        "dqn": DQN,
        "ars": ARS,
    }


def load_agents(models, map_name=DEFAULT_MAP):
    """Load every agent in `models` that has been trained on `map_name`."""
    loaded_agents = {}
    for key, model in models.items():
        file_name = f"{agent_dir(map_name)}/{key}"
        if os.path.exists(f"{file_name}.zip"):
            loaded_agents[key] = model.load(file_name)
    return loaded_agents


def create_env(model1, model2, render_mode, map_name=DEFAULT_MAP):
    # User input will not work with no display initialized
    if model1 == "user" or model2 == "user":
        assert render_mode == "human", "keyboard players need a window"
    return TestEnv(model1, model2, render_mode, map_name=map_name)


def run_test(model1, model2, env, steps):
    obs = env.reset()
    n = env.obs_size
    for _ in range(steps):
        if model1 == "user" and model2 == "user":
            actions = None
        elif model1 == "user":
            actions, _states = model2.predict(obs[n:])
        elif model2 == "user":
            actions, _states = model1.predict(obs[:n])
        else:
            action1, _states = model1.predict(obs[:n])
            action2, _states = model2.predict(obs[n:])
            actions = [action1, action2]
        obs, done, info = env.step(actions)
        if done:
            break
    s1, s2 = env.scores
    print(f"Final score - red: {s1}, blue: {s2}")
    env.close()


CONTROLS = {
    "first": "wasd + left shift to go heavy",
    "second": "the arrow keys + space or right shift to go heavy",
}


def make_statement(choices, num):
    statement = f"Your choices for the {num} agent:\n"
    for i, name in enumerate(choices):
        if name == "user":
            statement += f"{i}: user input (controlled with {CONTROLS[num]})\n"
        else:
            statement += f"{i}: {name}\n"
    statement += "Please enter the integer for your selected algorithm: "
    return statement


def read_int(prompt, valid=None, minimum=None):
    """Keep asking until the user enters an acceptable integer."""
    while True:
        try:
            value = int(input(prompt))
        except ValueError:
            print("Please enter a whole number.")
            continue
        if valid is not None and value not in valid:
            print("That's not one of the options.")
            continue
        if minimum is not None and value < minimum:
            print(f"Please enter a number of at least {minimum}.")
            continue
        return value


def pick_agent(choices, num):
    """Ask the user to pick from `choices` and return the chosen name."""
    pick = read_int(make_statement(choices, num), valid=range(len(choices)))
    print("-----------------")
    return choices[pick]


def pick_map():
    """Ask which map to play on and return its name."""
    names = list(MAPS)
    if len(names) == 1:
        return names[0]
    statement = "Choose a map:\n"
    for i, name in enumerate(names):
        statement += f"{i}: {MAPS[name].title} - {MAPS[name].description}\n"
    statement += "Please enter the integer for your selected map: "
    pick = read_int(statement, valid=range(len(names)))
    print("-----------------")
    return names[pick]


def get_steps():
    return read_int(
        "Enter an integer for how many steps (30 per second) you would like to simulate: ",
        minimum=0,
    )


def test(map_name=DEFAULT_MAP):
    agents = load_agents(model_classes(), map_name)
    # Menu numbers come from this list, so they always match what is printed
    choices = list(agents.keys()) + ["user"]

    pick1 = pick_agent(choices, "first")
    pick2 = pick_agent(choices, "second")

    agent1 = "user" if pick1 == "user" else agents[pick1]
    agent2 = "user" if pick2 == "user" else agents[pick2]

    steps = get_steps()
    env = create_env(agent1, agent2, render_mode="human", map_name=map_name)
    run_test(agent1, agent2, env, steps=steps)
