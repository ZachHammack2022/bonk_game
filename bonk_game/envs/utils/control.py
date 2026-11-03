from bonk_game.envs.utils.training import train_models, check_agents
from bonk_game.envs.utils.testing import pick_map, test


def game_loop():
    map_name = pick_map()

    # Agents are trained separately for each map
    if not check_agents(map_name):
        print("Training your agents for this map. This should take 10-15 minutes.\n \n")
        train_models(map_name)
    else:
        print("Your agents are already trained! We can go straight to testing.\n \n")

    test(map_name)
