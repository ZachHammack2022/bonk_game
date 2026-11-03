import argparse
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

from bonk_game.envs.utils.maps import MAPS

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Play bonk, or train AI agents for it.")
    parser.add_argument("--train", metavar="MAP", choices=list(MAPS),
                        help=f"train AI agents for a map ({', '.join(MAPS)}) instead of playing")
    parser.add_argument("--terminal", action="store_true",
                        help="use the old text menus instead of the game window")
    args = parser.parse_args()

    if args.train:
        from bonk_game.envs.utils.training import train_models
        train_models(args.train)
    elif args.terminal:
        from bonk_game.envs.utils.start import run_game
        run_game()
    else:
        from bonk_game.ui.app import run
        run()
