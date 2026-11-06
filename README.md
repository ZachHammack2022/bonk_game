[![main](https://github.com/ZachHammack2022/bonk_game/actions/workflows/tests.yml/badge.svg?branch=main&event=push)](https://github.com/ZachHammack2022/bonk_game/actions/workflows/tests.yml?query=branch%3Amain+event%3Apush) [![staging](https://github.com/ZachHammack2022/bonk_game/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/ZachHammack2022/bonk_game/actions/workflows/deploy.yml)

# bonk

A tiny physics brawler for the browser, inspired by bonk.io: 2 to 10 balls on a map, everyone trying to knock everyone else off. Play it at **[bonk-game.fly.dev](https://bonk-game.fly.dev)**.

Under the hood it's a small but complete multiplayer game: a Python server runs every match with [Box2D](https://box2d.org) physics at 30 steps a second and streams it over WebSockets; your browser runs the same physics ([planck.js](https://piqnt.com/planck.js/), Box2D's JavaScript port) to predict your own ball, so it reacts instantly even with lag. The same physics is a [Gymnasium](https://gymnasium.farama.org/) env for training AI agents, and trained agents can play online next to the built-in bots.

This README is in four parts:

1. **[Play](#play)**: running it, and how the game works.
2. **[Run a server](#run-a-server)**: hosting, deploys, watching it, accounts, security.
3. **[Learn how it works](#learn-how-it-works)**: a guided tour of the ideas in the code (networking, prediction, servers, auth, security, testing), with where to read and what to try.
4. **[Develop](#develop)**: tests, CI, maps, training, and the code layout.

---

## Play

### Quick start

```
pip install -r requirements-server.txt
python -m bonk_game.server            # http://localhost:8000 (--port to change)
```

Open the page, pick a name and press **Play**. You'll see every game going: join one, or press **New game** to make your own and send friends the invite link. That's all anyone needs: the server runs the game, and the browser only sends your keys and draws what comes back.

### Getting into a game

- **Play** opens the game list. Search by room, host, player or 4-letter code (Enter joins), filter by mode or map.
- **New game** makes a room: name it, and make it **public** (anyone can join) or **private** (listed with a lock; joining needs the password, which the server makes up). **Copy invite link** gives a link with the password in it, so friends get straight in.
- **The host** (★, whoever made the room) picks the mode, map and settings, fills open seats with bots (Easy, Medium or Hard), and presses **Start match**. They can rename the room, switch it between public and private, remove people (they can't come back), and **End match** at any time (say, to change the map without waiting for bots to finish).
- **Joining mid-match**: you take over a bot's seat, keeping its colour and score (straight away in Lives, Knockouts and Crown; at the next round otherwise), or watch until the next match.
- **← Lobby** during a match steps out while a bot plays for you; **← Leave** leaves the room. If you refresh or lose connection, you get your seat back; after 30 seconds away you leave.
- After a match everyone can vote to play again, and **Killcam** replays the final knockout in slow motion.

### Modes

| Mode | How it works |
|---|---|
| Free-for-all | On most maps a ball that's knocked out sits out the rest of the round, and the last one standing scores. (On Classic, where you respawn, the point goes to whoever last hit you.) First to N points. |
| Teams | Red against Blue, up to 5 a side. The last team standing scores the round (on Classic, every knockout scores for the other side). Bumping a teammate off doesn't count. |
| Lives | N lives each, respawning until they run out. Last ball left wins. |
| Knockouts | N minutes, respawning; the most knockouts wins. A tie goes to overtime: the next knockout wins. |
| Crown | One player wears the crown and scores a point a second. Bump the wearer to steal it; knock them out and it's yours. First to N seconds wins. |

The respawning modes don't work on Sinking Swing, whose floor is gone by the end of a round. A ball that respawns is held still and untouchable for 2 seconds, so you can see where you are.

A knockout counts for whoever last hit you in the past 3 seconds; if nobody did, you just fell. The results screen hands out awards: most knockouts, hardest hit, butterfingers (most falls with nobody near) and survivor.

The host can also set the **round time** (when the sudden-death walls close in), **gravity**, **speed** (normal is 75% of the original, which was too quick to plan anything) and **power-ups**: ⚡ speed, 🎈 float, 🪨 iron (heavy without being slow) and 👊 punch (the next ball you bump goes flying).

### Controls

| | Move / jump | Go heavy |
|---|---|---|
| Keyboard | W A S D or the arrow keys | Space or Shift |
| Gamepad | left stick or d-pad; A jumps | B, X, a bumper or a trigger |
| Touch | drag anywhere on the left half (pushing up jumps) | touch the right half |

Hold **heavy** for as long as you like: you're 5x heavier, so you hit harder and get knocked around less, but you move far more slowly (about a sixth of your running speed). Let go and you're light again at once. On a gamepad, Y waves, Start opens settings, and A votes for a rematch. Press 1-4 for emotes, Enter or T to chat, Esc for settings, M to mute.

### Your profile

**Profile** (top right, or click your ball) has three tabs:

- **Ball**: colour, pattern, trail, hat and knockout effect. Nearly everything is for everyone; a few things (any colour, some patterns, the sparkle trail, the cap, confetti) are for signed-in players. On your own screen your ball is always your colour.
- **Stats**: wins, knockouts, falls, hardest hit, awards, how you do per mode, and your last 50 matches.
- **Settings**: volume, screen shake, ping display, key bindings, **colourblind mode** (every ball gets its own pattern) and **high-contrast colours** (Okabe and Ito's palette).

It's all kept in your browser, no sign-up needed. **Sign in with Google** (bottom of the profile) to keep it on the server, the same on every device; **Download my data** and **Delete account** are in Stats. `/privacy` and `/terms` say what's kept.

### Chat and safety

Everyone in a room can chat (in the lobby, and over the match for a few seconds). Names and chat go through a word filter: an offensive name becomes "Player 42", and offensive words in chat are starred out. Click **⋯** next to anyone to **mute** them (on your screen only) or **report** them. It catches the common cases, not everything.

### Maps

| Map | Players | |
|---|---|---|
| Classic | 2-8 | A box with a bouncy floor and ceiling and deadly side walls. You can fly. Push people into the walls. |
| Floating Platform | 2-6 | One platform. Knock them off. |
| Sliding Platform | 2-6 | A platform with bumper posts that slides on a rail; rock it to fling people. |
| Sinking Swing | 2-6 | A floor with a launch pad that sinks away, and a swing to survive on. |
| Ramp Rumble | 2-8 | A halfpipe with springy bumpers overhead. |
| Grand Stage | 4-10 | A wide stage for a crowd, with bumpers in the corners. |
| Double Decker | 4-10 | A short upper deck above a long lower one. |

Apart from Classic, the maps float in open space, bonk-style: fall off the bottom or go off the sides and you're out until the next round. "Up" is a small hop, and held in the air it hovers, so you float but can't climb. These numbers were measured from a recording of bonk.io. Rounds last 45 seconds (Classic gives you 30 to score); then it's **sudden death** and red walls close in.

You can make your own maps as JSON files: see [Making maps](#making-maps).

---

## Run a server

### On Fly.io

`fly.toml` and `deploy/fly.sh` are set up for [Fly.io](https://fly.io). [Install flyctl](https://fly.io/docs/flyctl/install/), make an account, then:

```
./deploy/fly.sh bonk-yourname iad     # app name (it's in the address), then a region
```

Pick the region nearest your players (`fly platform regions`). The first run makes the app and prints a **metrics token**; keep it. Every run builds the Dockerfile, deploys one small machine (`shared-cpu-1x`, 512 MB, about 10 full rooms) and runs a smoke test against `https://bonk-yourname.fly.dev`. The machine stops when nobody's connected and starts on the next visit (the first load takes a few seconds), so it costs little when idle.

Accounts and metrics history live on a volume. Make it once: `fly volumes create bonk_data --size 1 --region iad -a <app>`. Fly snapshots it daily.

**Elsewhere** (Render, Railway, a VPS behind nginx or Caddy): run the `Dockerfile` (`docker build -t bonk . && docker run -p 8000:8000 bonk`), a single instance (rooms live in memory), over HTTPS, with `BONK_TRUST_PROXY=1` behind a proxy, a health check on `/healthz` and a stop timeout over 120 s.

### Deploys and updates

- **Staging**: every merge to `main` deploys to `https://bonk-game-staging.fly.dev` (`.github/workflows/deploy.yml`), and a smoke test checks it.
- **Production**: Actions → deploy → Run workflow → `production`. It deploys `main` only if its tests passed on that commit.
- **No dropped matches**: on SIGTERM the server stops taking connections, lets running matches finish (up to `BONK_DRAIN_SECONDS`, 120), then exits. Open tabs reconnect and get their room back. Tabs running the old client are told to refresh.
- **Check any deploy**: `python -m bonk_game.server.smoke https://your-server` loads the page, plays a few seconds against a bot, and prints the ping.

Set up once: make the staging app (`./deploy/fly.sh bonk-game-staging iad` plus its volume), then add a deploy token (`fly tokens create org`) as the repository secret `FLY_API_TOKEN`.

### Watching it

- **`/admin`**: paste the metrics token and see what's happening now (players, rooms, matches, tick time, bandwidth) and charts for the last hour to 90 days, with restarts marked. It's sampled every minute into `BONK_METRICS_DB`.
- **`/metrics`**: the same numbers in Prometheus format (`?format=json` for JSON), with `Authorization: Bearer <token>`.
- **Logs**: one JSON object per line (rooms, matches, errors with tracebacks, sign-ins, reports). `fly logs -a <app>`.
- **Player reports** at `/api/reports`, and **playtest reports** at `/api/playtest` (both with the token). See [Playtesting](#playtesting-with-friends).

### Settings

| Variable | Default | |
|---|---|---|
| `BONK_METRICS_TOKEN` | (none) | protects `/metrics`, `/admin` and the report endpoints. Make it long and random (`fly.sh` does). |
| `BONK_METRICS_DB` | in memory | where `/admin`'s history is kept (`/data/metrics.db` on Fly) |
| `BONK_TRUST_PROXY` | off | `1` behind a proxy, so limits see each visitor's real IP |
| `BONK_MAX_ROOMS` | 500 | rooms open at once |
| `BONK_ROOMS_PER_IP` | 10 | new rooms per IP per minute |
| `BONK_MAX_MEMBERS` | 16 | people in a room, players and watchers |
| `BONK_CONNECTIONS_PER_IP` | 20 | open connections per IP |
| `BONK_MESSAGES_PER_SECOND` / `BONK_MESSAGE_BURST` | 60 / 120 | messages per connection; one that keeps going over is closed |
| `BONK_WS_COMPRESS` | 1 | compress WebSocket messages (0: 25% less CPU, 3x the bandwidth) |
| `BONK_DRAIN_SECONDS` | 120 | how long a restart waits for matches to finish |
| `BONK_PLAYTEST` | 1 | collect playtest reports |

### Accounts (sign in with Google)

Optional: without these the server runs with guests only.

| Variable | |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | both set turns accounts on. Keep the secret in `fly secrets set`. |
| `BONK_DB` | the SQLite file (`/data/bonk.db` on Fly, on the volume) |
| `BONK_PUBLIC_URL` | the site's address, e.g. `https://bonk-game.fly.dev` (recommended: sign-in then always returns there) |
| `BONK_CONTACT` | an email for the privacy page (Google's review wants one) |
| `BONK_GOOGLE_SITE_VERIFICATION` | Search Console's "HTML tag" code, to prove you own the site |

Getting the Google client (once, about 10 minutes, at [console.cloud.google.com](https://console.cloud.google.com)):

1. Make a project.
2. **OAuth consent screen** (or **Google Auth Platform → Branding**): External, app name "bonk", your email as contact, `https://<site>/privacy` and `https://<site>/terms`. Scopes `openid`, `email`, `profile`. In **Testing** only listed test users can sign in; **Publish** to open it up.
3. **Credentials → OAuth client ID**, type Web application, redirect URI `https://<site>/auth/google/callback` (and `http://localhost:8000/auth/google/callback` for local).
4. `fly secrets set GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... -a <app>`.
5. For your app's name on Google's screen: set `BONK_CONTACT`, add a URL-prefix property in [Search Console](https://search.google.com/search-console), pick HTML tag, set `BONK_GOOGLE_SITE_VERIFICATION`, deploy, then Verify.

For staging, add its callback URL to the client and set the same secrets on `bonk-game-staging`.

### Security checklist

The server is built to be left running (see [Security](#11-security-what-stops-people-breaking-it) for how). What's left to you:

- [ ] `BONK_METRICS_TOKEN` is long and random, on every app (`python3 -c 'import secrets; print(secrets.token_urlsafe(24))'`).
- [ ] `GOOGLE_CLIENT_SECRET` and `FLY_API_TOKEN` are only in Fly secrets and GitHub secrets, never in the repo.
- [ ] GitHub → Settings → Code security: turn on **Dependabot alerts** and **Dependabot security updates**, so you hear about (and get fix PRs for) vulnerable dependencies while you're away.
- [ ] `main` requires the `merge-ready` check, and only you can push or run the production deploy.
- [ ] Glance at `/admin` and `/api/reports` now and then.

### Playtesting with friends

After every match each browser sends a short report: its ping, late states, how far its own ball was corrected (rubber-banding), frame rate, lost connections and the device. Nobody is asked anything: it's sent by itself. JavaScript errors are sent as they happen. No IP addresses are kept.

```
python -m bonk_game.server.playtest_report https://bonk-yourname.fly.dev --token <metrics token>
fly logs -a bonk-yourname --no-tail | python -m bonk_game.server.playtest_report -
```

That writes them up in Markdown: a row per report, medians by device, errors grouped, and a list of things to look at. The in-memory list is lost on deploy, so write it up first (or use the logs).

A good session: 3–6 friends on different networks (home Wi-Fi, a phone on mobile data, someone far away) and devices, a few full matches across maps and modes, then the write-up, alongside what people tell you.

---

## Learn how it works

bonk is small enough to read in an afternoon but does most of what a real online game has to. Each topic below says what the problem is, how bonk solves it, where to read, and something to try. They roughly build on each other.

```
 browser (60 fps)                                   server (30 steps/s)
 ┌──────────────────────────────┐   WebSocket   ┌─────────────────────────────┐
 │ input.js   keys → {"input"}  │ ────────────▶ │ web.py   one socket per tab │
 │                              │               │ room.py  lobby, chat, rules │
 │ net.js     predict your ball │               │          the tick loop:     │
 │ physics.js (planck.js)       │               │ match.py   step Box2D world │
 │                              │ ◀──────────── │ delta.py   state → changes  │
 │ clock.js   when to draw      │  state / "d"  │                             │
 │ draw.js    blend + render    │   30 per s    │ accounts.py, auth.py (SQLite│
 └──────────────────────────────┘               │  + Google sign-in)          │
                                                └─────────────────────────────┘
```

### 1. The server is in charge

**Problem.** If each browser decided where its own ball went, anyone could cheat by editing their copy, and two browsers would disagree about who hit whom.

**How bonk does it.** The server is *authoritative*: it runs the only real copy of every match. Browsers send only which buttons are held (`{"type": "input", "b": [0,1,0,0,0]}`), and only when they change. Each room runs an asyncio loop (`Room.run_match`) that steps the Box2D world 30 times a second (each step is 4 smaller Box2D steps, so fast balls don't pass through things), snapshots it, and sends it to everyone. If the loop falls badly behind, it skips ahead rather than trying to catch up, so a hiccup doesn't turn into a fast-forward.

**Read.** `bonk_game/server/room.py` (`run_match`, `handle`), `match.py`, `envs/utils/world.py` and `stepping.py`.

**Compare.** This is how .io games (agar.io, slither.io) and most competitive games work. The alternative, *peer-to-peer lockstep* (everyone simulates and only inputs are shared), suits RTS games but breaks down with physics that must match bit for bit.

### 2. The protocol: what goes over the wire

**Problem.** 30 full snapshots a second to every player adds up, and JSON is wordy.

**How bonk does it.** One WebSocket per tab, JSON text messages:

- The first message is `hello`: the client version, a random **token** (kept in localStorage, so a refresh rejoins as the same person), name and password. The server answers `welcome`, the lobby and the chat so far.
- During a match the server sends a full `state` every 3 seconds (a *keyframe*) and a **delta** (`"d"`) in between with only what changed: typically the balls and nothing else. A browser that missed something waits for the next keyframe. This cut the JSON by about 4x.
- The state is turned into JSON **once** and the same text goes to everyone; each player's copy gets only their own ball's speeds appended (`"you"`), which prediction needs.
- WebSocket compression (permessage-deflate) shrinks what's left to about 40%. A full room of 10 costs about 2 KB/s per player, 17 kbit/s.
- `ping` / `pong` every second measures the round trip.

**Read.** `web.py` (`websocket`, and the protocol at the top of the file), `delta.py` and `static/delta.js` (the same algorithm twice; `tests/test_delta.py` checks they rebuild every state identically).

**Compare.** Big .io games use **binary** messages (positions packed into a few bytes) and send each player only what's **near them**, because they have thousands of objects on a huge map. bonk's arena fits on one screen with at most 10 balls, so JSON plus deltas plus compression is small enough and much easier to debug.

### 3. Smooth motion from 30 updates a second

**Problem.** States arrive 30 times a second, unevenly (the network adds *jitter*), but the screen draws at 60 or more. Drawing each state as it lands looks jerky.

**How bonk does it.** *Interpolation*: the browser draws the match slightly **in the past**, blending between the two states either side of that moment. How far in the past is a trade-off: too little and a late state leaves nothing to blend toward (everything freezes); too much and everything lags. So `clock.js` measures how late states arrive and picks the moment by which 95% of the last 10 seconds of states had arrived, plus a tick. A steady connection draws about 40 ms behind; a jittery one waits longer (up to 250 ms more). The clock changes speed by at most 6% to reach a new delay, so nothing visibly jumps. If a state is later than even that, `draw.js` *extrapolates* for up to 0.1 s along the way things were moving, then waits.

**Read.** `static/clock.js` (the long comment at the top is the design), `static/js/draw.js`. Tests: `tests/test_clock.py`, `tests/test_interp.py`.

**Try.** Open the game with `?net=bad`, which pretends you're on a poor connection, and watch the other balls stay smooth.

### 4. Predicting your own ball

**Problem.** Interpolation works for everyone else, but your own ball would only react once your key press had gone to the server and the result had come back: a full round trip, 100 ms or more. Controls would feel like steering through mud.

**How bonk does it.** *Client-side prediction*. The browser keeps the same physics the server runs (Box2D, as planck.js) and, every frame:

1. takes the latest state from the server, which is a little old;
2. replays the buttons you've pressed since then, which the server hasn't used yet (`net.inputs` remembers when they changed);
3. draws your ball where that ends up.

The whole level is in the prediction: slopes, bumpers, moving platforms, and the other balls moving on as they were, so riding the slider or bumping someone is predicted too. When the next server state arrives and disagrees (say a bot shoved you in a way your browser couldn't know), the difference is **faded out over 0.1 s** instead of snapping (*reconciliation*). A big jump, like a respawn, is treated as a teleport and taken straight away.

**Read.** `static/js/net.js` (`predictFrom`, `ownPosition`), `static/physics.js`. `tests/test_predict.py` replays recorded matches through the browser's physics and checks it lands where the server did.

**Try.** `?net=far` (200 ms round trip) feels almost local. Then add `&predict=0` to turn prediction off and feel the difference.

**Compare.** Many .io games skip this: their slow, mouse-steered movement hides the lag. Fighting and shooting games predict, and some also *rewind* the server to judge hits from each player's point of view (lag compensation). bonk doesn't rewind: the server's view of a bump is final.

### 5. Living with bad networks

**Problem.** WebSockets run on TCP, which delivers everything in order. When a packet is lost, everything behind it waits for the resend (*head-of-line blocking*), so a lost packet looks like a stall followed by a burst.

**How bonk does it.** The playback clock (3) absorbs stalls, prediction (4) keeps your own ball responsive, and the server keeps only the latest input you sent, so a burst of old ones does no harm. To develop against this without a bad connection, `static/netsim.js` fakes one inside the browser:

| `?net=` | round trip added | jitter | stalls | like |
|---|---|---|---|---|
| `wifi` | 30 ms | ±15 ms | 150 ms, every ~30 s | a decent home connection |
| `mobile` | 80 ms | ±40 ms | 400 ms, every ~15 s | a phone on 4G |
| `far` | 180 ms | ±10 ms | none | another continent, wired |
| `bad` | 150 ms | ±80 ms | 800 ms, every ~8 s | weak signal |

Or set each part: `?lag=150&jitter=40&stall=400&stall_every=10` (`&seed=7` repeats the same "random" network). `node tests/web/network.js` plays a match in a real browser on each and prints what the playtest report saw. On `bad`, for example, frames where everything froze went from 35.5% with a fixed 50 ms delay to 2.4% with the adaptive clock.

**Compare.** Games that need the lowest latency use UDP (WebRTC data channels or WebTransport in browsers), where a lost packet is just skipped. That's a lot more machinery; few browser games bother.

### 6. Reconnects, restarts and deploys

**Problem.** People refresh, phones drop Wi-Fi, and the server has to be updated, all without wrecking matches.

**How bonk does it.**

- **Refresh or drop-out**: your token gets your seat back, and a Medium bot plays for you meanwhile. After 30 s away your place goes.
- **Server restart**: on SIGTERM the server drains: no new connections, running matches finish (up to 120 s), then everyone is told it's restarting. Their tabs reconnect to the new server with `reopen`, and the room is rebuilt with the same code, host and settings.
- **New client code**: every file URL ends in `?v=<hash of the client files>`, so browsers can cache them forever and still pick up a new version after a deploy. A tab running old code is told to refresh by its `hello`'s version check.

**Read.** `room.py` (`join`, `disconnect`, `drain`), `web.py` (`client_version`, `_shutdown`). The browser test kills and restarts the server mid-session to check all of this.

### 7. How much can one server take?

**Problem.** Knowing when you'll run out, and of what.

**How bonk does it.** `python -m bonk_game.server.load_test --sockets` runs more and more rooms of 10 bots over real WebSockets until the server can't keep up. On one core of a cloud VM:

| rooms of 10 | CPU (1 core) | tick avg / p99 | on the wire per room | keeps up |
|---|---|---|---|---|
| 1 | 4% | 0.53 / 1.06 ms | 20 KB/s | yes |
| 10 | 33% | 0.44 / 1.07 ms | 22 KB/s | yes |
| 20 | 58% | 0.38 / 0.86 ms | 22 KB/s | yes |
| 30 | 82% | 0.32 / 0.78 ms | 21 KB/s | barely |
| 40 | 89% | 0.25 / 0.64 ms | 21 KB/s | no |

**What it means.** CPU runs out first, not bandwidth: a room of 10 uses about 3% of a core, a quarter of it compressing messages. Python runs everything on one event loop, one core. A small shared machine runs about 10 full rooms (100 people). The next step up would be more processes, each owning some rooms. (This table predates the move to Box2D, which costs about 10% more CPU per room.)

**Watch it live.** The late-ticks chart on `/admin` shows a server falling behind.

### 8. Watching a running server

**Problem.** When it's live and you're not looking, how do you know it's healthy, and why it wasn't?

**How bonk does it.**

- **Structured logs**: one JSON object per line (`metrics.event`), so a log viewer can filter `"event": "match_ended"` or find every error with its traceback.
- **Metrics**: counters and gauges (`metrics.Stats`), including tick-time p99 and bytes on the wire (counted *after* compression by wrapping the socket's `write`). Served as Prometheus text for real monitoring tools, and as JSON.
- **History**: a sample every minute in SQLite (`metrics.History`), bucketed for charts. Counters restart at 0 when the server does, so the bucketing detects restarts and counts across them.
- **From the players' side**: playtest reports measure what the server can't see, like rubber-banding and frame rate.

**Read.** `metrics.py`, `admin/admin.js` (hand-drawn SVG charts, no chart library), `playtest.py`, `static/js/report.js`.

### 9. Signing in without passwords

**Problem.** Keeping accounts means keeping secrets safe. Passwords are the riskiest thing to store.

**How bonk does it.** It stores none: you sign in with Google using **OpenID Connect**, the *authorization code flow with PKCE*:

1. `/auth/google` sends you to Google with a random `state` (so the reply can't be forged by another site), a `nonce` (so a token can't be replayed), and a PKCE challenge (so a stolen code is useless without the secret verifier), all remembered in a short-lived cookie.
2. Google sends you back with a code. The server swaps it (with its client secret and the verifier) for an **ID token**, and checks its signature against Google's published keys, that it's for this app, current, and carries our nonce.
3. The server starts a **session**: a random cookie that's `HttpOnly` (scripts can't read it), `SameSite=Lax` (other sites can't send it with their requests) and `Secure`. Only a **hash** of it is stored, so a leaked database doesn't let anyone sign in.

Guests come first: your profile lives in your browser, and signing in merges it into your account. Changes to an account (PUT, POST, DELETE) are refused unless the `Origin` header is this site.

**Read.** `auth.py` (the docstring walks the flow), `accounts.py`, `profiles.py` and `static/profile.js` (the same validation twice; `tests/test_profile.py` checks they agree).

### 10. Keeping a chat room civil

**Problem.** Any game with names and chat gets abuse.

**How bonk does it.** One filter for names and chat (`moderation.py`): a profanity list with look-alike spellings, minus words games need ("kill", "noob"), plus our own list for slurs hidden in longer words or spelled f.u.c.k. Offensive names are replaced, offensive words are starred out. Players can mute (on their screen only) and report; reports are kept with what happened in the room lately. Hosts can remove people, and a removed signed-in player can't come back on any device. Others see you only by a public id, never your seat's token.

### 11. Security: what stops people breaking it

**The threat model.** Anyone on the internet can open the site, run their own client, and send whatever they like. Nothing they send can be trusted.

| Attack | Defence | Where |
|---|---|---|
| Cheating by editing the client | the server runs the game; clients only send buttons | `room.py`, `match.py` |
| Malformed or oversized messages | 4 KB message limit; every field type- and range-checked; unknown fields ignored | `web.py`, `room.py`, `lobby.py` |
| Flooding | per-connection message rate (60/s), per-IP connection and room limits, chat and report limits | `limits.py` |
| Code injection in names or chat (XSS) | user text is only ever set as `textContent`, never HTML; a Content-Security-Policy allows only this site's scripts | `static/js/*`, `web.py` |
| Clickjacking (framing the site to trick clicks) | `X-Frame-Options: DENY` and `frame-ancestors 'none'` | `web.py` |
| Cross-site requests acting as you (CSRF) | `SameSite` cookies and an `Origin` check on every change | `auth.py` |
| Another site's page opening a WebSocket as you | the account cookie only counts from this site's own pages | `web.py` |
| Stolen session database | only hashes of session tokens are stored | `accounts.py` |
| SQL injection | every query uses parameters | `accounts.py` |
| Guessing room passwords or the metrics token | constant-time comparison; 10 wrong guesses a minute per IP | `room.py`, `web.py` |
| Downgrading to HTTP | Fly forces HTTPS; HSTS tells browsers to stay on it | `fly.toml`, `web.py` |
| A vulnerable dependency | exact versions pinned; Dependabot opens update PRs | `constraints.txt`, `.github/dependabot.yml` |
| A malicious pull request stealing deploy secrets | PR checks run without secrets; deploys only from `main`; workflow tokens are read-only | `.github/workflows/` |

**Known limits.** Right after a restart, the first person back can claim a room's host. Players can inflate their own stats by uploading an edited profile (cheating, not a break-in). The container runs as root inside Fly's isolated VM.

### 12. Bots and AI agents

**The built-in bot** (`bonk_game/ui/bot.py`) doesn't learn: it gets "inside" its target (between them and the middle), shoves outward, goes heavy just before impact, and heads for the swing when the floor sinks. Easy, Medium and Hard differ in how quickly it reacts, how well it aims, and how often it goes heavy; Hard also braces for heavy hits.

**Trained agents.** Every map is a Gymnasium env (`bonk_game/bonk-<map>-v0`), so any reinforcement-learning library can train on it. `main.py --train <map>` trains PPO, A2C, DQN and ARS agents with Stable Baselines 3, against a mix of the built-in bots, a weak "bad" agent and snapshots of themselves (*self-play*). Because the server runs the same physics, a trained agent can take a seat in an online match.

**Read.** `bonk_game/envs/training_env.py`, `testing_env.py`, and [Training](#training-agents) below.

### 13. Managing the codebase

A few habits keep a project like this working as it grows:

- **One source of truth, checked twice.** Where the browser and the server must agree (physics, deltas, profile validation, the playback clock), the tests run both, Python and JavaScript, and compare: `test_predict.py`, `test_delta.py`, `test_profile.py`, `test_clock.py`.
- **Real-browser tests.** `tests/web/e2e.js` drives two Chromium windows through Playwright: a full match, a reload mid-match, a phone-sized lobby, a server restart, and no page errors.
- **No build step.** The client is plain scripts sharing one global scope. To still catch typos, `eslint.config.js` reads the names each file declares and complains only about names nobody declares.
- **Pinned versions.** Requirements give ranges; `constraints.txt` and `package-lock.json` pin exact versions, so a new release can't break anything until someone bumps it and CI checks the bump.
- **Optimistic CI.** A pull request needs only lint (about a minute) to merge; the slower jobs run alongside as a heads-up and in full on `main`. If `main` goes red, production deploys refuse it.
- **Staging first.** Every merge goes to a staging app automatically; production is a deliberate button.

---

## Develop

### Tests and lint

```
pip install -r requirements-test.txt -c constraints.txt
python -m pytest                      # the Python tests

npm ci && npx playwright install chromium
node tests/web/e2e.js                 # the browser test
node tests/web/network.js             # a match on each simulated network

ruff check .                          # Python lint (rules in pyproject.toml)
npm run lint                          # browser lint (eslint.config.js)
```

**CI** (`.github/workflows/tests.yml`) runs `lint` on every pull request (the `merge-ready` check `main` requires), plus whichever of `test` (pytest), `web` (the browser test) and `training` (a moment of real training) the change touches. Everything runs on `main` after each merge; add the `full-ci` label to a pull request to run it all first.

### The desktop game and training

The desktop game is for training and testing agents, not for playing online.

1. Install Python 3.10 or newer, clone the repo, and in it run:
   ```
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt && pip install -e .
   python3 main.py
   ```
   (On macOS, `defaults write org.python.python ApplePersistenceIgnoreState NO` once stops a warning.)
2. Pick a map and 2 to 10 players: you, bots at Easy, Medium or Hard, or trained agents. Esc pauses. `--terminal` gives the old text menus.

<a id="training-agents"></a>**Training agents.** `python3 main.py --train <map>` (classic, platform, slider, swing, ramps, or any map file) takes 10-15 minutes per map; add `--steps 20000` for a quick, weak try, or `--opponents bad` to train only against the weak "bad" agent. Agents are saved to `agents/` (Classic) or `agents/<map>/`, show up as players in the desktop game, and join online matches if the server has stable-baselines3 installed. To retrain from scratch, delete the map's agent folder. `python -m bonk_game.envs.check_env` runs SB3's env checker on every map. On maps with moving parts, agents also see a few map values (for Sinking Swing, how far the floor has sunk and the swing's angle and speed).

### Making maps

Maps can be JSON files. Every `*.json` in `bonk_game/maps/`, in a `maps/` folder where you run the game, or in a folder listed in `BONK_MAPS` is loaded at startup and shows up in the lobby, in `main.py --train <name>`, and as the env `bonk_game/bonk-<name>-v0`. A file with a mistake is skipped with a message saying what's wrong; `python -m bonk_game.check_map my_map.json` checks one.

`bonk_game/maps/ramps.json` is a complete example. The screen is 680 x 480, y points down, and players are 40 px across.

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
    "jump_speed": 10, "max_speed": 28,
    "players": [2, 10]              // fewest and most players it's for
  },
  "spawn": [260, 420, 200, 328],    // [left, right, top, bottom] players spawn in
  "pieces": [ ... ]
}
```

(The comments are only there to explain it; JSON files can't have comments.)

| Piece | Shape keys |
|---|---|
| `block` | `"rect": [left, top, right, bottom]` |
| `slope` | `"center": [x, y], "size": [w, h], "angle": degrees` (positive is clockwise) |
| `post` | `"foot": [x, y], "size": [w, h], "lean": degrees` (positive leans right) |
| `bumper` | `"center": [x, y], "radius": r` |
| `swing` | `"pivot": [x, y], "length": 245, "seat_width": 96` |
| `slider` | `"travel": 140, "mass": 6, "rail": true, "pieces": [pieces that move together]` |

`block`, `slope`, `post` and `bumper` also take `"bounce"` (0-1.5, default 0.3), `"friction"` (0-1, default 0.04), `"launch"` (a speed: pads fire you out of their top, bumpers away from their centre), `"kill": true`, and `"color"` (`platform`, `post`, `pad`, `pit`, `wood`, `hazard`, `rail`, or `[r, g, b]`).

Players are spread over the spawn box, one per ball-sized cell; a box 220 x 88 px or bigger fits all 10. For things a file can't describe (like Sinking Swing's sinking floor), subclass `OpenMap` (or `Map` for a walled arena) in `bonk_game/envs/utils/maps.py` and add it to `MAPS`.

### Code layout

```
bonk_game/
  envs/                    the game itself, as Gymnasium envs
    utils/world.py           each map's Box2D world, and bonk's rules on top (grip, jumping, launch pads, what kills)
    utils/stepping.py        one 1/30 s step: 4 Box2D steps
    utils/maps.py, bodies.py the maps and the pieces they're made of
    utils/arena.py           arena size, actions, spawning
    training_env.py          the env agents train on
    testing_env.py           the 2-10 player env matches are played in
  maps/                    map files (JSON)
  ui/                      the desktop game (pygame) and the built-in bot (bot.py)
  server/                  the web server
    web.py                   routes, the WebSocket, security headers, /admin
    room.py                  a room: members, lobby, chat, the match loop
    lobby.py, modes.py       settings, seats, teams, colours; the game modes
    match.py, powerups.py    running a match; pickups
    delta.py, scene.py       sending only what changed; the world as shapes for the browser
    auth.py, accounts.py     Google sign-in; accounts and sessions (SQLite)
    profiles.py, cosmetics.py  profiles and stats; what you can wear
    moderation.py            the word filter and player reports
    limits.py                rate and size limits
    metrics.py               logs, /metrics, and its history
    playtest.py, playtest_report.py, smoke.py, load_test.py   checking how it plays and holds up
    admin/                   the /admin page
    static/                  the browser client (no build step)
      index.html, style.css
      physics.js             the browser's copy of the physics (on vendor/planck.min.js)
      clock.js, netsim.js, delta.js, profile.js   shared with the Python tests
      js/                    the client's scripts, listed at the top of js/core.js
tests/                     pytest, plus tests/web/ (Playwright)
deploy/fly.sh, fly.toml, Dockerfile   hosting
.github/                   CI, deploys, Dependabot
main.py                    the desktop game and training
```
