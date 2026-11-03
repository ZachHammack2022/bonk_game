[![tests](https://github.com/ZachHammack2022/bonk_game/actions/workflows/tests.yml/badge.svg)](https://github.com/ZachHammack2022/bonk_game/actions/workflows/tests.yml)

This is a working version of bonk.io, a popular online physics-based platform game. This was created using pygame, mostly from scratch aside from the collision functions. This environment supports single agent RL using Gymnasium and Stable Baselines 3.

Currently, only one bonk.io env exists, but multiple envs could easily be created. There are options for multiplayer, AI agent vs user, and AI vs AI (same or different training algorithms). Tournaments are supported for AI agents only. User cannot interact in tournament yet.

## How it plays
Run `python3 main.py` to open the game. Pick a map, choose who's playing (a human, the built-in Bot, or any AI agents you've trained for that map), and pick how many points win.

Two balls fight to knock each other out. Going **heavy** makes you 5x heavier for a moment, so you hit harder and get knocked around less, but you move more slowly and can't go heavy again until it wears off.

| | Move / jump | Go heavy |
|---|---|---|
| Red | W A S D | Left Shift |
| Blue | Arrow keys | Space or Right Shift |

Esc pauses, M mutes. Everything works with the mouse too.

## Maps
You pick a map when you run `main.py`. Agents are trained separately for each map.

**Classic**: a box with a bouncy floor and ceiling and deadly side walls. "Up" is a thrust, so you can fly. Push your opponent into a wall to score; a point respawns only the player who died. First to 100 wins.

The other maps float in open space, bonk-style. There are no walls: you die if you fall off the bottom, go off the left or right of the screen, or get launched way above the top. You can't fly on them either: "up" is a jump, and it only works while you're standing on something. Each death gives the other player a point and restarts the round, and the first to 5 wins.

**Floating Platform**: one platform, nothing else. Knock your opponent off.

**Sliding Platform**: a platform with an outward-leaning bumper post at each end that slides left and right on a rail. Every hit and every roll shoves it, so you can rock it back and forth to build momentum and fling your opponent. Going heavy shoves it much harder. Jump over a post to leave (or get thrown over one).

**Sinking Swing**: a floor with a hole in the middle, a launch pad at the bottom of the hole, and a swing hanging above it all.
- After about 5 seconds the floor (with the hole and pad) starts sinking, and eventually drops off the screen.
- Fall through the hole and the pad fires you back up.
- Jump into the swing to survive once the floor is gone. Kick the swing (going heavy kicks much harder) or jump out and knock your opponent off it.

**Round timer**: rounds last 45 seconds. On Classic, which has no rounds, you get 30 seconds to score. When time runs out it's **sudden death**: red walls close in from both sides, and touching one kills you. Whoever gets pushed into a wall first loses. Change the limit with `round_time` on the map class (0 turns it off).

### Adding a map
Subclass `OpenMap` (or `Map` for a walled arena) in `bonk_game/envs/utils/maps.py` and add it to `MAPS` at the bottom of that file. It then shows up in the main menu, in `tournament.py --map <name>`, and as the gym env `bonk_game/bonk-<name>-v0`. `bonk_game/envs/utils/bodies.py` has building blocks: rectangles (`Block`), rotated rectangles for slopes and leaning posts (`OrientedBlock`), round bumpers (`Bumper`), a platform that slides when pushed, and a swing. Pieces can move, bounce, have friction, kill, or launch players (pinball-style for bumpers).

## To run
1. Install Python 3.10 or newer
2. Clone repo (if you're unfamiliar, click the green button above and download the zip. Then click the zip to open the files once you download it.)
3. Open terminal, navigate to the working directory (bonk_game-main), and run "python3 -m venv ./venv" to create a virtual environment to install our dependencies.
4. Run "source ./venv/bin/activate"
5. Run "pip install -r requirements.txt"
6. Run "pip install -e ." to make the gym environment
7. Run "defaults write org.python.python ApplePersistenceIgnoreState NO" if on macOS.
8. Run "python3 main.py" to play. You can play against a friend or the built-in Bot straight away.
9. To play against AI agents, train them for a map with "python3 main.py --train <map>" (maps: classic, platform, slider, swing). It takes 10-15 minutes per map. They then show up as players in the game. For a quick try, add "--steps 20000" (the agents will be weak). Agents train against a mix of opponents: the built-in bot, the map's "bad" agent and snapshots of themselves (self-play). Add "--opponents bad" to train only against the bad agent, as older versions did.
10. Once you have trained agents, you can run a tournament: "python3 tournament.py --map <map>". This puts your trained agents against one another to find the winner!

The old text menus are still available with "python3 main.py --terminal".

To retrain from scratch, delete the map's agent folder (`agents` for Classic, `agents/<map>` for the others) and run `python3 main.py` again.

## How training works
Every map is a [Gymnasium](https://gymnasium.farama.org/) env: `gymnasium.make("bonk_game/bonk-v0")` for Classic and `bonk_game/bonk-<map>-v0` for the others. `python -m bonk_game.envs.check_env` runs Stable Baselines 3's env checker on all of them.

A weak PPO "bad" agent is trained first. The PPO, A2C, DQN and ARS agents are then each trained against it (it controls the blue player in `BonkEnv`). Agents are saved to `./agents/<name>.zip` (Classic) or `./agents/<map>/<name>.zip` (other maps).

On maps with extra moving parts, agents also see a few map values: for Sinking Swing, how far the floor has sunk and the swing's angle and speed.

## Tests
The tests only need a few packages, and run on every push and pull request via GitHub Actions:

```
pip install -r requirements-test.txt
python -m pytest
```

## Code layout
- `bonk_game/ui/`: the game window: screens and HUD (`app.py`), the visual style (`painter.py`, `theme.py`), sound effects (`sound.py`) and the built-in Bot (`bot.py`)
- `bonk_game/envs/utils/arena.py`: arena size, action table and spawning shared by every env
- `bonk_game/envs/utils/maps.py`: the maps
- `bonk_game/envs/utils/bodies.py`: moving/bouncy blocks, the sliding platform and the swing
- `bonk_game/envs/utils/mechanics.py`: classic collision physics and player-vs-player collisions
- `bonk_game/envs/training_env.py`: the gym env agents train on
- `bonk_game/envs/testing_env.py`: the two-player env used for playing and for tournament matches
