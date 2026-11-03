"""The playback clock (static/clock.js): what moment of the match to draw.

States are sent every tick; netsim.js decides when each one arrives, as it
does in the browser with ?net=. Each test draws at 60 frames a second and
counts frames that had no state to blend toward (everything would stop).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
STATIC = Path(__file__).resolve().parent.parent / "bonk_game" / "server" / "static"
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")

TICK = 1000 / 30


def node(body):
    script = (f"const C = require({json.dumps(str(STATIC / 'clock.js'))});\n"
              f"const N = require({json.dumps(str(STATIC / 'netsim.js'))});\n"
              f"const TICK = {TICK};\n{body}")
    res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def play(net, seconds=120, fixed=None):
    """Play `seconds` of states over a pretend network. Returns how often the
    moment drawn had no newer state yet, how often it was past guessing
    too, and the delays used. fixed: draw that many ms behind the newest
    arrival instead (how it worked before clock.js)."""
    return node(f"""
    const link = N.link({json.dumps(net)}, N.rng(7));
    const arrivals = [];
    for (let k = 0; k < {seconds} * 30; k++) arrivals.push([k, link.arrival(k * TICK) + 1000]);
    const clock = C.make(TICK);
    let next = 0, late = 0, frozen = 0, frames = 0;
    const delays = [], drawn = [];
    const newest = [];
    for (let now = 1000; now < {seconds} * 1000 + 1000; now += 1000 / 60) {{
      while (next < arrivals.length && arrivals[next][1] <= now) {{
        clock.arrive(arrivals[next][0], arrivals[next][1]); newest.push(arrivals[next]); next++;
      }}
      if (!newest.length) continue;
      const top = newest[newest.length - 1][0];
      let at;
      if ({json.dumps(fixed)} !== null) {{
        // the newest state that had arrived {json.dumps(fixed)} ms ago, and how far past it
        const then = now - {json.dumps(fixed)};
        let j = newest.length - 1;
        while (j > 0 && newest[j][1] > then) j--;
        const [tk, t0] = newest[j];
        at = tk + (newest[j + 1] ? (then - t0) / (newest[j + 1][1] - t0) : 1.01);
      }} else {{
        at = clock.tick(now);
        delays.push(clock.delay(now));
      }}
      drawn.push(at);
      frames++;
      if (now > 11000) {{  // (once the clock has seen a full window)
        if (at > top) late++;
        if ({json.dumps(fixed)} === null ? clock.paused : at > top + C.GUESS_MS / TICK) frozen++;
      }}
    }}
    delays.sort((a, b) => a - b);
    let back = 0;
    for (let k = 1; k < drawn.length; k++) if (drawn[k] < drawn[k - 1]) back++;
    const counted = frames - 660;
    console.log(JSON.stringify({{ late: 100 * late / counted, frozen: 100 * frozen / counted, back,
      median: delays.length ? delays[delays.length >> 1] : null }}));
    """)


def test_a_steady_connection_draws_close_behind():
    r = play({"lag": 120})
    assert r["late"] == 0
    assert r["median"] <= 45  # a tick (33 ms) and a margin


def test_a_jittery_connection_waits_long_enough():
    net = {"lag": 80, "jitter": 40}
    before = play(net, fixed=50)
    after = play(net)
    assert before["late"] > 10  # a fixed 50 ms isn't enough for this
    assert after["late"] < 4
    assert after["frozen"] < 0.5
    assert 50 < after["median"] < 200


def test_the_odd_stall_doesnt_make_everything_lag():
    # wifi: a little jitter, and a 150 ms stall every ~30 s
    r = play({"lag": 30, "jitter": 15, "stall": 150, "stall_every": 30})
    assert r["median"] < 70
    assert r["frozen"] < 1


def test_time_never_runs_backwards():
    for net in ({"lag": 80, "jitter": 40}, {"lag": 150, "jitter": 80, "stall": 800, "stall_every": 8}):
        assert play(net, seconds=60)["back"] == 0


def test_changing_delay_is_gradual_and_a_big_jump_snaps():
    out = node("""
    const clock = C.make(TICK);
    const steps = [];
    let tick = 0, now = 0, prev = null, prevNow = 0;
    // 10 s steady, then states start coming 100 ms later and stay jittery
    for (; now < 20000; now += 1000 / 60) {
      while (tick * TICK <= now) {
        const extra = tick * TICK > 10000 ? 100 + ((tick * 37) % 60) : 0;
        clock.arrive(tick, tick * TICK + 50 + extra); tick++;
      }
      const at = clock.tick(now);
      if (prev !== null) steps.push(((at - prev) * TICK) / (now - prevNow));
      prev = at; prevNow = now;
    }
    // A reconnect: the server's ticks are suddenly a second ahead
    const before = clock.tick(now);
    for (let k = 0; k < 30; k++) clock.arrive(tick + 30 + k, now + k);
    const after = clock.tick(now + 30);
    console.log(JSON.stringify({ min: Math.min(...steps), max: Math.max(...steps), jump: (after - before) * TICK }));
    """)
    assert out["min"] >= 0.93 and out["max"] <= 1.07  # never more than 6 % fast or slow
    assert out["jump"] > 500  # (30 ms later, a second further on)


def test_a_connection_that_gets_worse_is_caught_quickly():
    out = node("""
    const clock = C.make(TICK);
    let late = 0, tick = 0;
    for (let now = 0; now < 30000; now += 1000 / 60) {
      // From 10 s on, every state takes 200 ms longer (the server fell behind)
      const shift = (k) => (k * TICK > 10000 ? 200 : 0);
      let top = -1;
      while (tick * TICK + 50 + shift(tick) <= now) { clock.arrive(tick, tick * TICK + 50 + shift(tick)); tick++; }
      top = tick - 1;
      const at = clock.tick(now);
      if (clock.paused) late += 1000 / 60;
    }
    console.log(JSON.stringify({ frozenMs: late }));
    """)
    assert out["frozenMs"] < 1500


def test_the_page_loads_the_clock_before_core():
    html = (STATIC / "index.html").read_text()
    assert html.index("/static/clock.js") < html.index("/static/js/core.js")
