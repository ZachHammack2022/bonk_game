"""The pretend network for testing on one machine (static/netsim.js)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
NETSIM = Path(__file__).resolve().parent.parent / "bonk_game" / "server" / "static" / "netsim.js"
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")


def node(body):
    script = f"const N = require({json.dumps(str(NETSIM))});\n{body}"
    res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def test_settings_come_from_the_address():
    out = node("""
    const p = (q) => N.fromParams(new URLSearchParams(q));
    console.log(JSON.stringify([p(""), p("?predict=0"), p("?net=mobile&seed=3"), p("?lag=150"),
      p("?net=far&jitter=50&seed=1"), p("?stall=500"), p("?lag=abc"), p("?net=nope")]));
    """)
    none, other, mobile, lag, far, stall_only, junk, unknown = out
    assert none is None and other is None and junk is None and unknown is None
    assert mobile == {"lag": 80, "jitter": 40, "stall": 400, "stall_every": 15, "name": "mobile", "seed": 3}
    assert lag["lag"] == 150 and lag["jitter"] == 0 and lag["name"] == "custom"  # ?lag= still works
    assert far["lag"] == 180 and far["jitter"] == 50
    assert stall_only["stall"] == 0  # a stall needs stall_every too


def arrivals(opts, every_ms=33, seconds=60):
    return node(f"""
    const l = N.link({json.dumps(opts)}, N.rng(5));
    const out = [];
    for (let t = 0; t < {seconds * 1000}; t += {every_ms}) out.push([t, l.arrival(t)]);
    console.log(JSON.stringify(out));
    """)


def test_messages_arrive_in_order_about_half_the_lag_later():
    out = arrivals({"lag": 100, "jitter": 40})
    delays = [a - t for t, a in out]
    assert all(b >= a for (_, a), (_, b) in zip(out, out[1:]))  # in order, like TCP
    assert min(delays) >= 50  # half the round trip each way
    mean = sum(delays) / len(delays)
    assert 60 < mean < 85  # plus half the jitter on average (a bit more, waiting in line)
    assert max(delays) < 50 + 20 * 6 + 33 * 6


def test_stalls_hold_messages_then_let_them_all_through():
    out = arrivals({"lag": 0, "jitter": 0, "stall": 400, "stall_every": 5}, seconds=120)
    delays = [a - t for t, a in out]
    held = [d for d in delays if d > 0]
    # About one stall every 5 s, each holding everything for up to 400 ms
    stalls = sum(1 for d0, d1 in zip(delays, delays[1:]) if d0 == 0 and d1 > 0)
    assert 12 <= stalls <= 40 and max(held) <= 400
    # Held messages arrive together, when the stall ends
    ends = [a for t, a in out if a > t]
    assert len(set(ends)) <= stalls


def test_same_seed_same_network():
    a = node("""
    const run = (seed) => { const l = N.link({lag: 80, jitter: 40, stall: 300, stall_every: 2}, N.rng(seed));
      return Array.from({length: 200}, (_, i) => l.arrival(i * 33)); };
    console.log(JSON.stringify([run(1), run(1), run(2)]));
    """)
    assert a[0] == a[1] != a[2]


def test_the_pipe_runs_callbacks_in_order():
    out = node("""
    const sim = N.make({lag: 60, jitter: 60, stall: 0, stall_every: 0, seed: 9});
    const got = [];
    for (let i = 0; i < 50; i++) sim.down(() => got.push(i));
    setTimeout(() => console.log(JSON.stringify(got)), 600);
    """)
    assert out == list(range(50))


def test_says_what_its_simulating():
    out = node("""console.log(JSON.stringify([
      N.describe(N.fromParams(new URLSearchParams("?net=mobile"))),
      N.describe(N.fromParams(new URLSearchParams("?lag=150")))]))""")
    assert out == ["Simulating mobile: +80 ms, ±40, 400 ms stalls every ~15 s", "Simulated network: +150 ms"]
