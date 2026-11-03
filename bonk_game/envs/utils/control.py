from bonk_game.envs.utils.training import train_models, check_agents
from bonk_game.envs.utils.testing import test


def game_loop():
    # Train various agents to play bonk.io
    if not check_agents():
        print("Training your agents. This should take 10-15 minutes.\n \n")
        train_models()
    else:
        print("Your agents are already trained! We can go straight to testing.\n \n")

    test()
