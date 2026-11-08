# Should state messages be binary? (the wire benchmark)

**Short answer: not yet.** Binary would make no difference players can
feel. Its real benefit is the same CPU saving as switching compression off,
while keeping today's small messages. That's worth having once server and
bandwidth bills matter, not before.

Measured November 2026 on a 4-core cloud machine (Python 3.13, aiohttp 3.14),
with the four options below. Raw numbers are in `results/`.

| option | what it is |
|---|---|
| **json+deflate** | today: JSON (delta.py), compressed per connection (permessage-deflate) |
| **json** | JSON, not compressed |
| **bin** | the prototype binary format (`proto.py`, `proto.js`), not compressed |
| **bin+deflate** | binary, compressed |

## What we found

**1. Compression is the cost, not JSON.** Python's `json.dumps` is written in C,
so writing JSON costs the same as packing binary (`results/micro.md`).
Server CPU to send one tick to everyone in a room:

| room | game itself | json+deflate | json | bin | bin+deflate |
|---|---|---|---|---|---|
| classic, 4 players | 170 µs | 31 µs | 8 µs | 8 µs | 29 µs |
| grand, 8 players | 385 µs | 84 µs | 15 µs | 13 µs | 68 µs |
| decks, 10 players | 834 µs | 106 µs | 18 µs | 14 µs | 85 µs |

The game itself is the people-playing cost per tick. Sending is 9–18% of a
room's CPU today, and 2–5% without compression.

**2. On a real server, either way of dropping compression saves about 9–11
points of CPU** (`results/sockets.md`). This is the real game, rooms and aiohttp
on one pinned core, with browsers in other processes. It's 5 runs per option,
taken in turn, and the "vs today" numbers are paired by run.

| load | json+deflate | json | bin | bin+deflate |
|---|---|---|---|---|
| 40 rooms of 4 | 78.4% CPU, 10.2 kbit/s a player | −9.0 pts, **30.4 kbit/s** | −9.0 pts, 12.5 kbit/s | −2.1 pts, 7.3 kbit/s |
| 20 rooms of 8 | 70.8% CPU, 12.4 kbit/s a player | −7.8 pts, **38.2 kbit/s** | −10.6 pts, 11.9 kbit/s | −4.5 pts, 7.9 kbit/s |

Those CPU numbers mean about **10–19% more rooms per core** (today's 1.96% to
binary's 1.78% per room of 4, and 3.54% to 2.98% per room of 8). Every browser
got its 30 states a second in every run. All 325,000 states that were checked
rebuilt the match exactly.

**3. Binary without compression is as small as compressed JSON.** About 50 B a
player at 4 players, against 145 B for plain JSON. Over the wire, every message
also carries about 75 B of TLS, TCP and IP headers whatever its format. So
dropping compression from JSON takes the real bytes from about 126 to about 223
per message, not a tripling.

**4. Phones: no difference** (`results/phone.md`). On a throttled iPhone-sized
Chromium, turning messages into states takes about 0.2–0.4 ms of each second of
play either way. Decompressing happens off the main thread.

**5. Latency: none.** Every option fits in one packet, so they all arrive at the
same moment.

**6. The capacity test is too noisy on a shared machine to rank the options.**
It reports the most rooms of 8 one core keeps up with, with one hiccup failing a
run (`results/capacity.md`, `results/capacity-bin-rerun.md`):

| json+deflate | json | bin | bin+deflate |
|---|---|---|---|
| 27, 24 | 27, 33 | 30, (failed at 15: one stall), 18, 27 | 30, 27 |

Use the fixed-load CPU numbers (point 2) instead. They're steady.

## What it means

- **Turning compression off alone** is a one-line change (`BONK_WS_COMPRESS=0`)
  for about 10% more players per core, at about 70–80% more bandwidth. At rough
  Fly prices (egress about $0.02/GB in North America and Europe and more
  elsewhere; a dedicated core about $30 a month for about 200 players), the extra
  bandwidth costs about 10 times what the CPU saves. **So don't.**
- **Binary** gets the CPU saving with today's bandwidth. That's the honest case
  for it, at about 2 days of work: the format agreed per connection in hello,
  with JSON as the fallback. **Worth it when you're scaling** (many machines,
  real egress bills), not for feel and not now.
- The bigger lever is the game itself, which is 80–95% of the server's CPU.
  Faster physics would do more than any change to the format.

## Running it

```bash
python -m bench.wire.bench check     # the prototype gives exactly the same messages and states (Python, JS, fuzzed)
taskset -c 0 python -m bench.wire.bench micro
python -m bench.wire.sockets fixed   # about 20 minutes
python -m bench.wire.sockets capacity  # about 25 minutes
node tests/web/wire_bench.js         # phone side (after check)
```
