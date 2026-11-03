"""Check map files: python -m bonk_game.check_map path/to/map.json [...]"""
import sys

from bonk_game.envs.utils.map_files import main

if __name__ == "__main__":
    sys.exit(main())
