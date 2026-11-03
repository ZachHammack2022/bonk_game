This is a working version of bonk.io, a popular online physics-based platform game. This was created using pygame, mostly from scratch aside from the collision functions. This environment supports single agent RL using OpenAI gym and Stable Baselines 3.

Currently, only one bonk.io env exists, but multiple envs could easily be created. There are options for multiplayer, AI agent vs user, and AI vs AI (same or different training algorithms). Tournaments are supported for AI agents only. User cannot interact in tournament yet.

## How it plays
Two balls fight to knock each other out. Going **heavy** makes you 5x heavier for a moment, so you hit harder and get knocked around less, but you move more slowly and can't go heavy again until it wears off.

| | Move | Go heavy |
|---|---|---|
| Player 1 (red) | W A S D | Caps Lock |
| Player 2 (blue) | Arrow keys | Space |

Close the window at any time to end the match.

## Maps
You pick a map when you run `main.py`. Agents are trained separately for each map.

**Classic**: a box with a bouncy floor and ceiling and deadly side walls. "Up" is a thrust, so you can fly. Push your opponent into a wall to score; a point respawns only the player who died. First to 100 wins.

**Sinking Swing**: a floor with a hole in the middle, a launch pad at the bottom of the hole, and a swing hanging above it all.
- After about 5 seconds the floor (with the hole and pad) starts sinking, and eventually drops off the screen.
- You can't fly here: "up" is a jump, and it only works while you're standing on the floor, the pad, or the swing seat.
- Fall through the hole and the pad fires you back up.
- Jump into the swing to survive once the floor is gone. Kick the swing (going heavy kicks much harder) or jump out and knock your opponent off it.
- You die if you fall off the bottom, go off the left or right of the screen, or get launched way above the top.
- Each death gives the other player a point and restarts the round. First to 5 wins.

### Adding a map
Subclass `Map` in `bonk_game/envs/utils/maps.py` and add it to `MAPS` at the bottom of that file. It then shows up in the main menu, in `tournament.py --map <name>`, and as the gym env `bonk_game/bonk-<name>-v0`. `bonk_game/envs/utils/bodies.py` has building blocks: rectangles that can move, bounce, have friction or launch players, and a swing.

## To run
1. Install python 3.9
2. Clone repo (if you're unfamiliar, click the green button above and download the zip. Then click the zip to open the files once you download it.)
3. Open terminal, navigate to the working directory (bonk_game-main), and run "python3.9 -m venv ./venv" to create a virtual environment to install our dependencies.
4. Run "source ./venv/bin/activate"
5. Run "pip install -r requirements.txt"
6. Run "pip install -e ." to make the gym environment
7. Run "defaults write org.python.python ApplePersistenceIgnoreState NO" if on macOS.
8. Run "python3 main.py". This will train your agents and allow you to begin testing.
9. Once you have trained your agents, you can run a tournament. Run "python3 tournament.py". This will put your trained agents against one another to find the winner! Add `--map swing` to hold it on the Sinking Swing map.

To retrain from scratch, delete the map's agent folder (`agents` for Classic, `agents/swing` for Sinking Swing) and run `python3 main.py` again.

## How training works
A weak PPO "bad" agent is trained first. The PPO, A2C, DQN and ARS agents are then each trained against it (it controls the blue player in `BonkEnv`). Agents are saved to `./agents/<name>.zip` (Classic) or `./agents/<map>/<name>.zip` (other maps).

On maps with extra moving parts, agents also see a few map values: for Sinking Swing, how far the floor has sunk and the swing's angle and speed.

## Tests
The physics tests only need numpy, pygame and pytest:

```
pip install pytest
python -m pytest
```

## Code layout
- `bonk_game/envs/utils/arena.py`: arena size, action table, spawning and rendering shared by every env
- `bonk_game/envs/utils/maps.py`: the maps
- `bonk_game/envs/utils/bodies.py`: moving/bouncy blocks and the swing
- `bonk_game/envs/utils/mechanics.py`: classic collision physics and player-vs-player collisions
- `bonk_game/envs/training_env.py`: the gym env agents train on
- `bonk_game/envs/testing_env.py`: the two-player env used for playing and for tournament matches
