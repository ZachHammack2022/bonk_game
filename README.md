[![tests](https://github.com/ZachHammack2022/bonk_game/actions/workflows/tests.yml/badge.svg)](https://github.com/ZachHammack2022/bonk_game/actions/workflows/tests.yml)

bonk is a tiny physics brawler, inspired by bonk.io, that you play in the browser with friends: 2 to 10 balls on a map, everyone trying to knock everyone else off. A Python server runs every match. The same physics is a Gymnasium env for training AI agents with Stable Baselines 3, and trained agents can join online matches alongside the built-in bots.

## Play online with friends
The server runs every match; your browser just sends your keys and draws what it gets back, so friends only need a link.

```
pip install -r requirements-server.txt
python -m bonk_game.server            # http://localhost:8000 (--port to change)
```

Open the page, pick a name and **Create a room**. You get a 4-letter room code; **Copy invite link** and send it to friends. Whoever made the room is the host (marked ★): they pick the mode, the map and the settings, and add bots (Easy, Medium or Hard) to fill seats, up to 10 players. Then **Start match**.

| Mode | How it works |
|---|---|
| Free-for-all | On most maps a ball that's knocked out sits out the rest of the round, and the last one standing scores. (On Classic, where you respawn, the point goes to whoever last hit you.) First to N points. |
| Teams | Red team against Blue team, up to 5 a side, each in its own colours. The last team standing scores the round (on Classic, every knockout scores for the other side). Bumping a teammate off doesn't count. Click **Switch to …** in the lobby to change sides. |
| Lives | Everyone has N lives and respawns straight away until they run out. Last ball left wins. The sudden-death walls still close in when the round clock runs out. |
| Knockouts | N minutes, respawning; the most knockouts wins. A tie goes to overtime: the next knockout wins. |
| Crown | One player wears the crown and scores a point a second. Bump the wearer to steal it; knock them out and it's yours. First to wear it for N seconds in total wins. |

The respawning modes (Lives, Knockouts and Crown) don't work on Sinking Swing, whose floor is gone by the end of a round.

The host can also set the **round time** (how long before the sudden-death walls close in, or off), **gravity** (low, normal or high) and turn on **power-ups**. With power-ups on, a pickup appears every few seconds; touch it for a few seconds of ⚡ speed (push harder, faster top speed), 🎈 float (much less gravity), 🪨 iron (as heavy as a heavy ball the whole time, but you move as if you weren't) or 👊 punch (the next ball you bump goes flying).

A knockout counts for whoever last hit you in the past 3 seconds; if nobody did, you just fell. The feed in the top right shows who knocked out whom, and the results screen hands out awards: most knockouts, hardest hit, butterfingers (most falls with nobody near) and survivor (knocked out the fewest times).

Going **heavy** makes you 5x heavier for a moment, so you hit harder and get knocked around less, but you move more slowly and can't go heavy again until it wears off.

| Move / jump | Go heavy |
|---|---|
| W A S D or the arrow keys | Space or Shift |

- On phones and tablets there are on-screen buttons. M mutes.
- Your own ball reacts as soon as you press a key: the browser predicts where the server will put it and smooths out any difference when the server's answer arrives. Your ping is in the bottom-right corner. To try it with a slow connection, add `?lag=150` to the page address (150 ms of fake delay); `?predict=0` turns prediction off for comparison.
- If you refresh or lose connection, you get your seat back; a Medium bot plays for you while you're gone. After 30 seconds away you leave the room.
- People who join during a match watch it and play in the next one.
- **Your ball:** pick a favourite colour and a pattern (stripes, dots, eyes and more) with **Customize** on the home page, or by clicking your ball in the lobby. They're saved in your browser (no sign-up needed) and come with you into every room; you get your colour whenever it's free.
- **Settings** (⚙, or Esc): volume, mute, screen shake, show ping, and your keys. The arrow keys and Shift always work as well.
- Press 1-4 (or the buttons in the corner) for emotes during a match.
- After a match everyone can vote to play again; the next one starts when everyone has voted (or the host starts it). The host can also remove someone from the room (✕ next to their name); they can't rejoin it.
- Trained agents can play online too: if the server has stable-baselines3 installed and agents in `./agents`, they show up next to the bots.

### Running it on the internet
Run it on any host that supports WebSockets. The `Dockerfile` builds the server (`docker build -t bonk . && docker run -p 8000:8000 bonk`), and it reads the port from `PORT`. Rooms live in memory, so run a single instance; restarting the server ends any rooms in progress.

The server limits how much any one visitor can use. Each limit can be changed with an environment variable:

| Variable | Default | |
|---|---|---|
| `BONK_MAX_ROOMS` | 500 | rooms open at once |
| `BONK_ROOMS_PER_IP` | 10 | new rooms per IP per minute |
| `BONK_MAX_MEMBERS` | 16 | people in a room, players and watchers |
| `BONK_CONNECTIONS_PER_IP` | 20 | open connections per IP |
| `BONK_MESSAGES_PER_SECOND` / `BONK_MESSAGE_BURST` | 60 / 120 | messages per connection; a connection that keeps going over is closed |

Behind a proxy (Fly, Render, nginx), set `BONK_TRUST_PROXY=1` so the limits see each visitor's real IP rather than the proxy's.

## The desktop game (for training)
`python3 main.py` opens a local window, used for training and testing agents: try a map, and watch trained agents play against each other, the bots, or you. Pick a map, choose 2 to 10 players (you, a bot at Easy, Medium or Hard, or any agents trained for that map) and how many points win. Esc pauses.

## Maps
You pick a map when you run `main.py`. Agents are trained separately for each map.

**Classic**: a box with a bouncy floor and ceiling and deadly side walls. "Up" is a thrust, so you can fly. Push someone into a wall to score: the point goes to whoever last hit them (with two players, always the other player), and only the player who died respawns. First to 100 wins.

The other maps float in open space, bonk-style. There are no walls: you die if you fall off the bottom, go off the left or right of the screen, or get launched way above the top. You can't fly on them either: "up" is a jump, and it only works while you're standing on something. If you die you're out until the next round. The last ball standing scores and a new round starts; the first to 5 wins.

**Floating Platform**: one platform, nothing else. Knock your opponent off.

**Sliding Platform**: a platform with an outward-leaning bumper post at each end that slides left and right on a rail. Every hit and every roll shoves it, so you can rock it back and forth to build momentum and fling your opponent. Going heavy shoves it much harder. Jump over a post to leave (or get thrown over one).

**Ramp Rumble**: a halfpipe with springy bumpers overhead, made from a map file (see "Making maps" below). Ride the ramps and bounce in from above.

**Sinking Swing**: a floor with a hole in the middle, a launch pad at the bottom of the hole, and a swing hanging above it all.
- After about 5 seconds the floor (with the hole and pad) starts sinking, and eventually drops off the screen.
- Fall through the hole and the pad fires you back up.
- Jump into the swing to survive once the floor is gone. Kick the swing (going heavy kicks much harder) or jump out and knock your opponent off it.

**Round timer**: rounds last 45 seconds. On Classic, which has no rounds, you get 30 seconds to score. When time runs out it's **sudden death**: red walls close in from both sides, and touching one kills you. Whoever gets pushed into a wall first loses. Change the limit with `round_time` on the map class (0 turns it off).

### Making maps
Maps can be plain JSON files. Every `*.json` file in `bonk_game/maps/`, in a `maps/` folder next to where you run the game, or in any folder listed in the `BONK_MAPS` environment variable is loaded at startup. It shows up in the menu, in `main.py --train <name>`, and as the gym env `bonk_game/bonk-<name>-v0`. A file with a mistake is skipped with a message saying exactly what's wrong. To check one yourself, run `python -m bonk_game.check_map my_map.json`.

`bonk_game/maps/ramps.json` is a complete example. The screen is 680 x 480, with y pointing down, and players are 40 px across.

```json
{
  "name": "my_map",                 // lowercase, used in env and folder names
  "title": "My Map",                // shown in the menu (optional)
  "description": "One line pitch",  // optional
  "rules": {                        // all optional
    "movement": "jump",             // "jump" or "fly"
    "first_to": 5,
    "round_time": 45,               // seconds before sudden death; 0 = off
    "on_death": "new_round",        // or "respawn" (only the dead player)
    "jump_speed": 23.5, "max_speed": 28
  },
  "spawn": [260, 420, 200, 328],    // [left, right, top, bottom] players spawn in
  "pieces": [ ... ]
}
```

| Piece | Shape keys |
|---|---|
| `block` | `"rect": [left, top, right, bottom]` |
| `slope` | `"center": [x, y], "size": [w, h], "angle": degrees` (positive is clockwise, so the surface rises to the left) |
| `post` | `"foot": [x, y], "size": [w, h], "lean": degrees` (positive leans right) |
| `bumper` | `"center": [x, y], "radius": r` |
| `swing` | `"pivot": [x, y], "length": 245, "seat_width": 96` |
| `slider` | `"travel": 140, "mass": 6, "rail": true, "pieces": [blocks, slopes, posts, bumpers that move together]` |

`block`, `slope`, `post` and `bumper` also take these options:
- `"bounce"` (0-1.5, default 0.3) and `"friction"` (0-1, default 0.04);
- `"launch"`: a speed. Pads fire you out of their top face; bumpers fire you away from their centre, like pinball;
- `"kill": true`;
- `"color"`: one of `platform`, `post`, `pad`, `pit`, `wood`, `hazard`, `rail`, or `[r, g, b]`.

The comments in the example above are only there to explain it; JSON files can't contain comments.

Matches have up to 10 players. Each round they're spread over the spawn box, one per ball-sized cell; if the box is too small for everyone, the rest drop in from just above it. A box 220 x 88 px or bigger fits all 10 inside it.

For things a file can't describe (like Sinking Swing's sinking floor), subclass `OpenMap` (or `Map` for a walled arena) in `bonk_game/envs/utils/maps.py` and add it to `MAPS` at the bottom of that file. The pieces live in `bonk_game/envs/utils/bodies.py`.
## To run
1. Install Python 3.10 or newer
2. Clone repo (if you're unfamiliar, click the green button above and download the zip. Then click the zip to open the files once you download it.)
3. Open terminal, navigate to the working directory (bonk_game-main), and run "python3 -m venv ./venv" to create a virtual environment to install our dependencies.
4. Run "source ./venv/bin/activate"
5. Run "pip install -r requirements.txt"
6. Run "pip install -e ." to make the gym environment
7. Run "defaults write org.python.python ApplePersistenceIgnoreState NO" if on macOS.
8. Run "python3 main.py" to play. You can play against the built-in Bot straight away.
9. To play against AI agents, train them for a map with "python3 main.py --train <map>" (maps: classic, platform, slider, swing, ramps, plus any map files you add). It takes 10-15 minutes per map. They then show up as players in the game. For a quick try, add "--steps 20000" (the agents will be weak). Agents train against a mix of opponents: the built-in bot at all three difficulties, the map's "bad" agent and snapshots of themselves (self-play). Add "--opponents bad" to train only against the bad agent, as older versions did.

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

CI also plays the web version in a real browser (two players, a full match, a reload mid-match, a phone-sized lobby):

```
npm install --no-save playwright && npx playwright install chromium
node tests/web/e2e.js
```

## Code layout
- `bonk_game/ui/`: the game window: screens and HUD (`app.py`), the visual style (`painter.py`, `theme.py`), sound effects (`sound.py`) and the built-in Bot (`bot.py`)
- `bonk_game/envs/utils/arena.py`: arena size, action table and spawning shared by every env
- `bonk_game/envs/utils/maps.py`: the maps
- `bonk_game/envs/utils/bodies.py`: moving/bouncy blocks, the sliding platform and the swing
- `bonk_game/envs/utils/mechanics.py`: classic collision physics and player-vs-player collisions
- `bonk_game/envs/training_env.py`: the gym env agents train on
- `bonk_game/envs/testing_env.py`: the 2-10 player free-for-all env used for playing matches
- `bonk_game/envs/utils/controls.py`: player inputs (an agent's action or a set of held buttons)
- `bonk_game/server/`: the web server: rooms and the WebSocket protocol (`room.py`, `web.py`), running a match (`match.py`), the game modes (`modes.py`), power-ups (`powerups.py`), turning the world into shapes for the browser (`scene.py`), and the browser client (`static/`)
