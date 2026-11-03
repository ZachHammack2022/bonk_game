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

| | Move / jump | Go heavy |
|---|---|---|
| Keyboard | W A S D or the arrow keys | Space or Shift |
| Gamepad | left stick or d-pad; A jumps | B, X, a bumper or a trigger |

On a gamepad, Y waves, Start opens settings, and A votes to play again on the results screen. Any controller the browser knows (Xbox, PlayStation, Switch Pro and most others) works; press a button on it once the page is open.

- On phones and tablets there are on-screen buttons. M mutes.
- Your own ball reacts as soon as you press a key: the browser predicts where the server will put it and smooths out any difference when the server's answer arrives. Your ping is in the bottom-right corner. To try it on a worse connection, add `?net=mobile` to the page address (see [Simulating bad networks](#simulating-bad-networks)); `?predict=0` turns prediction off for comparison.
- If you refresh or lose connection, you get your seat back; a Medium bot plays for you while you're gone. After 30 seconds away you leave the room.
- People who join during a match watch it and play in the next one.
- **Your ball:** pick a favourite colour and a pattern (stripes, dots, eyes and more) with **Customize** on the home page, or by clicking your ball in the lobby. They're saved in your browser (no sign-up needed) and come with you into every room; you get your colour whenever it's free.
- **Your stats** (📊 on the home page): wins, knockouts, falls, your hardest hit, the awards you've won, how you do in each mode, and your last 50 matches (place, mode, map, knockouts, awards). Every match you play in is added when it ends. Like your ball and settings, they're kept in your browser, as one profile. **Save to a file** and **Add from a file** move them to another browser (adding the same file twice doesn't count it twice), and the same file can be added to an account once there are accounts.
- **Settings** (⚙, or Esc): volume, mute, screen shake, show ping, and your keys. The arrow keys and Shift always work as well.
- Press 1-4 (or the buttons in the corner) for emotes during a match.
- After a match everyone can vote to play again; the next one starts when everyone has voted (or the host starts it). The host can also remove someone from the room (✕ next to their name); they can't rejoin it.
- Trained agents can play online too: if the server has stable-baselines3 installed and agents in `./agents`, they show up next to the bots.

### Running it on the internet
Run it on any host that supports WebSockets. The `Dockerfile` builds the server (`docker build -t bonk . && docker run -p 8000:8000 bonk`), and it reads the port from `PORT`. Rooms live in memory, so run a single instance. Serve it over HTTPS: the page then connects with `wss://` by itself.

**Hosting it on Fly.io** (what `fly.toml` is set up for). [Install flyctl](https://fly.io/docs/flyctl/install/) and make a Fly account, then:

```
./deploy/fly.sh bonk-yourname ord     # app name (it's in the address), then a region
```

Pick the region nearest your players (`fly platform regions` lists them: `iad` Virginia, `ord` Chicago, `lax` Los Angeles, `lhr` London, `fra` Frankfurt…). The first run makes the app and prints a metrics token; keep it. Every run builds the Dockerfile, deploys it to one small machine (`shared-cpu-1x`, 512 MB, about 10 full rooms), and runs the smoke test against `https://bonk-yourname.fly.dev`, which is the link to send friends. Run the same command again to deploy an update: matches being played finish first. The machine stops when nobody has been connected for a while and starts again on the next visit (the first page load then takes a few seconds), so it costs little when idle. `fly logs -a bonk-yourname` shows the server's logs.

`fly.toml` sets `BONK_TRUST_PROXY=1`, HTTPS only, the `/healthz` check, and a stop timeout longer than the server's drain. Elsewhere (Render, Railway, a VPS behind nginx or Caddy), set the same yourself.

**Checking a deploy.** `python -m bonk_game.server.smoke https://your-server` loads the page, makes a room, connects over the WebSocket, plays a few seconds against a bot and prints the ping and how steadily states arrive from where you run it. It exits 1 if anything fails.

**Updating it.** Stop the server with SIGTERM (what Docker, Fly and most hosts send). It stops taking new connections, lets the matches being played finish (up to `BONK_DRAIN_SECONDS`, 120 by default; give your host a stop timeout a bit longer than that), tells everyone it's restarting, and exits. Open tabs reconnect to the new server and get their room back: same code, same host, same settings. Every client file's URL carries a hash of the client (`?v=...`), so browsers cache them for good but load the new ones after a deploy. A tab still running the old client is told to refresh, and does.

**Watching it.** The server logs one JSON object per line (room created/closed, match started/ended, errors with a traceback). `GET /metrics` reports rooms, people, matches running, tick time (average and p99), bytes sent (as JSON, and on the wire after compression) and more, in Prometheus' format (`/metrics?format=json` for JSON). Set `BONK_METRICS_TOKEN` to require `Authorization: Bearer <token>` for it.

The server limits how much any one visitor can use. Each limit can be changed with an environment variable:

| Variable | Default | |
|---|---|---|
| `BONK_MAX_ROOMS` | 500 | rooms open at once |
| `BONK_ROOMS_PER_IP` | 10 | new rooms per IP per minute |
| `BONK_MAX_MEMBERS` | 16 | people in a room, players and watchers |
| `BONK_CONNECTIONS_PER_IP` | 20 | open connections per IP |
| `BONK_MESSAGES_PER_SECOND` / `BONK_MESSAGE_BURST` | 60 / 120 | messages per connection; a connection that keeps going over is closed |
| `BONK_WS_COMPRESS` | 1 | compress WebSocket messages (see below) |
| `BONK_PLAYTEST` | 1 | collect playtest reports (see below); 0 turns them off |

Behind a proxy (Fly, Render, nginx), set `BONK_TRUST_PROXY=1` so the limits see each visitor's real IP rather than the proxy's.

### Playtesting with friends
After every match each browser sends the server a short report: its ping (median, p95 and jitter), how many states arrived late (over 100 ms after the last), how far its own ball had to be corrected when the server's answer came back (rubber-banding: corrections over 6 px, over 20 px and the worst), its frame rate, whether it lost connection, and the device (browser, screen size, network type, touch or controller). The results screen asks **How did that match feel?** (Smooth, OK, Laggy, Unplayable, and a note), sent along with the report. JavaScript errors are sent as they happen. Nothing else is collected; the reports carry the player's name but no IP address. They're logged (`"event": "playtest"` and `"client_error"`), and the latest 500 are at `GET /api/playtest` (same token as `/metrics`).

```
python -m bonk_game.server.playtest_report https://bonk-yourname.fly.dev --token <metrics token>
fly logs -a bonk-yourname --no-tail | python -m bonk_game.server.playtest_report -
```

writes them up in Markdown: a row per report, medians by device, how matches felt with everyone's notes, errors grouped, and a list of things to look at (ping p95 over 150 ms, late states, more than 3 corrections over 6 px a minute, any over 20 px, under 45 fps, lost connections, matches that felt laggy). The in-memory list starts again after a deploy, so write it up before deploying, or use the logs.

A playtest session:
1. Deploy, run the smoke test, and send the link to 3–6 friends: on different networks (home Wi-Fi, a phone on mobile data, someone far away) and devices (a laptop, a phone, a tablet, a controller).
2. Play a few full matches on different maps and modes, with and without bots and power-ups. Try a phone in portrait and landscape, and walk away from the Wi-Fi.
3. Ask everyone to pick how each match felt, and to say in the note anything that felt wrong: controls slow to respond, your ball jumping back (rubber-banding), others' balls stuttering, buttons hard to hit.
4. Write it up with `playtest_report` and add it, with what people said, to the tuning issue.

### Simulating bad networks
To see how the game plays on a worse connection without leaving your desk, add `?net=` to the page address:

| `?net=` | round trip added | jitter | stalls | like |
|---|---|---|---|---|
| `wifi` | 30 ms | ±15 ms | 150 ms, every ~30 s | a decent home connection |
| `mobile` | 80 ms | ±40 ms | 400 ms, every ~15 s | a phone on 4G |
| `far` | 180 ms | ±10 ms | none | another continent, wired |
| `bad` | 150 ms | ±80 ms | 800 ms, every ~8 s | weak signal |

Or set each part yourself: `?lag=150&jitter=40&stall=400&stall_every=10` (`?seed=7` gives the same "random" network every time). Messages stay in order, as over a real WebSocket: in a stall nothing arrives, then everything held up arrives at once, which is what a lost packet does. The page says what it's simulating in the top right corner, and playtest reports say so too.

`node tests/web/network.js` plays a match in a real browser on each of these and prints what the playtest report saw (it needs Playwright, as the browser test does). Before any tuning, against two Hard bots on Platform:

| network | ping median / p95 | late states /min | worst gap | frames frozen | your ball corrected >6 px /min | >20 px /min | worst correction |
|---|---|---|---|---|---|---|---|
| normal | 1 / 1 ms | 0.0 | 94 ms | 0.1% | 21.9 | 11.9 | 72 px |
| `wifi` | 56 / 75 ms | 0.0 | 78 ms | 1.8% | 89.9 | 20.0 | 150 px |
| `mobile` | 126 / 435 ms | 28.9 | 142 ms | 12.1% | 225.7 | 65.6 | 241 px |
| `far` | 194 / 206 ms | 0.0 | 77 ms | 0.8% | 81.8 | 17.9 | 312 px |
| `bad` | 284 / 633 ms | 129.6 | 718 ms | 32.4% | 182.6 | 76.6 | 463 px |

- **Frames frozen** is how often the browser had no newer state to move toward, so every ball stood still for a frame. Anything over a few percent looks like stutter: the 50 ms the browser draws behind the server isn't enough for jitter and stalls.
- **Corrections** are how far your own ball had to be moved when the server's answer came back (small ones fade in over 0.1 s). With no lag at all, they're bots bumping you, which your browser can't predict; more lag means each bump is found out later and is bigger.

### How big a server?
`python -m bonk_game.server.load_test --sockets` runs more and more rooms of 10 at once over real WebSockets until the server can't keep up, and prints what it used. The "browsers" ask for compression, as real ones do. Below: a 4-core cloud VM (the server is one process, so it uses one core), bots playing all 10 balls on Grand Stage.

| rooms of 10 | CPU (1 core) | tick avg / p99 | ticks per second | JSON per room | on the wire per room | keeps up |
|---|---|---|---|---|---|---|
| 1 | 4% | 0.53 / 1.06 ms | 30.1 | 51 KB/s | 20 KB/s (0.16 Mbit/s) | yes |
| 10 | 33% | 0.44 / 1.07 ms | 30.0 | 55 KB/s | 22 KB/s (0.17 Mbit/s) | yes |
| 20 | 58% | 0.38 / 0.86 ms | 30.1 | 55 KB/s | 22 KB/s (0.17 Mbit/s) | yes |
| 30 | 82% | 0.32 / 0.78 ms | 30.1 | 55 KB/s | 21 KB/s (0.17 Mbit/s) | yes, barely (event loop up to 37 ms late) |
| 40 | 89% | 0.25 / 0.64 ms | 28.4 | 54 KB/s | 21 KB/s (0.17 Mbit/s) | no |

Sending the whole state every tick instead (`--full`, how it worked before) takes about 214 KB/s of JSON per room, which compresses to 25 KB/s on the wire. With people instead of bots (`--players people`), 30 rooms use 70% of the core.

What that means:
- **CPU is what runs out first.** A room of 10 uses about 3% of a core. About a quarter of that is compressing messages, once for each connection. A small shared-CPU machine (1 vCPU, slower than this one: plan on half) runs about 10 full rooms, 100 people. Private rooms with friends are mostly 2-6 people, which costs less.
- **Bandwidth is cheap.** A player gets about 2 KB/s (17 kbit/s), so a full room sends 0.17 Mbit/s, and a 6-person hour is about 45 MB.
- `BONK_WS_COMPRESS=0` turns compression off: about 25% less CPU, but nearly 3 times the bandwidth (0.47 Mbit/s per full room).

## The desktop game (for training)
`python3 main.py` opens a local window, used for training and testing agents: try a map, and watch trained agents play against each other, the bots, or you. Pick a map, choose 2 to 10 players (you, a bot at Easy, Medium or Hard, or any agents trained for that map) and how many points win. Esc pauses.

## Maps
You pick a map in the lobby (or when you run `main.py`). Agents are trained separately for each map.

Each map says how many players it's for (below), and the lobby holds to it. Bots past a map's limit sit that match out (they're back on a bigger map), and so do people, who watch instead.

| Map | Players |
|---|---|
| Classic | 2-8 |
| Floating Platform, Sliding Platform, Sinking Swing | 2-6 |
| Ramp Rumble | 2-8 |
| Grand Stage, Double Decker | 4-10 |

**Classic**: a box with a bouncy floor and ceiling and deadly side walls. "Up" is a thrust, so you can fly. Push someone into a wall to score: the point goes to whoever last hit them (with two players, always the other player), and only the player who died respawns. First to 100 wins.

The other maps float in open space, bonk-style. There are no walls: you die if you fall off the bottom, go off the left or right of the screen, or get launched way above the top. You can't fly on them either: "up" is a jump, and it only works while you're standing on something. If you die you're out until the next round. The last ball standing scores and a new round starts; the first to 5 wins.

**Floating Platform**: one platform, nothing else. Knock your opponent off.

**Sliding Platform**: a platform with an outward-leaning bumper post at each end that slides left and right on a rail. Every hit and every roll shoves it, so you can rock it back and forth to build momentum and fling your opponent. Going heavy shoves it much harder. Jump over a post to leave (or get thrown over one).

**Ramp Rumble**: a halfpipe with springy bumpers overhead, made from a map file (see "Making maps" below). Ride the ramps and bounce in from above.

**Grand Stage**: a wide stage built for a crowd, with a small ledge in the middle and springy bumpers up in the corners.

**Double Decker**: a short upper deck above a long lower one with outward-leaning posts at its ends. Hold the top, or drop down and fight it out below.

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
    "jump_speed": 23.5, "max_speed": 28,
    "players": [2, 10]              // fewest and most players it's for
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

CI also plays the web version in a real browser (two players, a full match, a reload mid-match, a phone-sized lobby, a server restart):

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
- `Dockerfile`, `fly.toml`, `deploy/fly.sh`: hosting the web server (on Fly.io, or anywhere that runs Docker)
- `bonk_game/server/`: the web server: rooms and the WebSocket protocol (`room.py`, `web.py`), logs and `/metrics` (`metrics.py`), the load test (`load_test.py`), playtest reports and their write-up (`playtest.py`, `playtest_report.py`, and `static/js/report.js`), checking a deployed server (`smoke.py`), profiles and match history (`profiles.py`, the same rules as `static/profile.js` in the browser), pretending the network is worse (`static/netsim.js`, measured by `tests/web/network.js`), sending just what changed each tick (`delta.py`, and `static/delta.js` in the browser), running a match (`match.py`), the game modes (`modes.py`), power-ups (`powerups.py`), turning the world into shapes for the browser (`scene.py`), and the browser client (`static/`: `index.html`, `style.css`, `predict.js`, and the scripts in `js/`, listed at the top of `js/core.js`)
