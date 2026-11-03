"""Smaller state messages (issue #31): matches send what changed since the
last tick, and the browser (static/delta.js) rebuilds the same state as if
it had been sent whole."""
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from bonk_game.envs.utils.maps import MAPS
from bonk_game.server import delta
from bonk_game.server.match import Match
from bonk_game.server.room import Room

NODE = shutil.which("node")
DELTA_JS = Path(__file__).resolve().parent.parent / "bonk_game" / "server" / "static" / "delta.js"


def roundtrip(x):
    return json.loads(json.dumps(x, separators=(",", ":")))


def recorded(map_name, mode="ffa", ticks=900, power_ups=False, keyframe_every=None):
    """(full states, messages sent) for a bot match, as the browser gets them."""
    np.random.seed(1)
    n = min(6, MAPS[map_name].players[1])
    m = Match(map_name, [{"kind": "bot:hard", "name": f"b{i}"} for i in range(n)], 50,
              mode=mode, power_ups=power_ups)
    enc = delta.Encoder(keyframe_every)
    states, msgs = [], []
    for _ in range(ticks):
        events = m.tick()
        s = m.snapshot()
        s["events"] = events
        states.append(roundtrip(s))
        msgs.append(roundtrip(enc.encode(s)))
        if m.finished:
            break
    return states, msgs


def rebuild(msgs):
    out, last = [], None
    for msg in msgs:
        last = msg if msg["type"] == "state" else delta.apply(last, msg)
        out.append(last)
    return out


CASES = [(name, "ffa", False) for name in MAPS] + [
    ("platform", "crown", True), ("grand", "teams", True), ("classic", "lives", False),
    ("ramps", "knockouts", True)]


@pytest.mark.parametrize("map_name,mode,power_ups", CASES)
def test_changes_rebuild_every_state(map_name, mode, power_ups):
    states, msgs = recorded(map_name, mode, power_ups=power_ups)
    assert rebuild(msgs) == states
    kinds = [m["type"] for m in msgs]
    assert kinds[0] == "state" and kinds.count("d") > len(kinds) * 0.9


@pytest.mark.skipif(NODE is None, reason="needs node")
@pytest.mark.parametrize("map_name,mode,power_ups", [CASES[i] for i in (1, 2, 3, -4, -1)])
def test_the_browser_rebuilds_the_same_states(map_name, mode, power_ups):
    states, msgs = recorded(map_name, mode, ticks=400, power_ups=power_ups)
    script = f"""
    const D = require({json.dumps(str(DELTA_JS))});
    const msgs = JSON.parse(require("fs").readFileSync(0, "utf8"));
    let last = null;
    const out = msgs.map((m) => (last = m.type === "state" ? m : D.apply(last, m)));
    console.log(JSON.stringify(out));
    """
    res = subprocess.run([NODE, "-e", script], input=json.dumps(msgs), capture_output=True,
                         text=True, check=True)
    assert json.loads(res.stdout) == states


@pytest.mark.skipif(NODE is None, reason="needs node")
def test_the_browser_ignores_a_change_it_cant_place():
    script = f"""
    const D = require({json.dumps(str(DELTA_JS))});
    const s = {{ type: "state", tick: 5, players: [[1, 2, 0, 1]], scores: [0] }};
    const before = JSON.stringify(s);
    console.log(JSON.stringify([
      D.apply(s, {{ type: "d", tick: 7 }}),             // missed tick 6
      D.apply(null, {{ type: "d", tick: 6 }}),          // nothing yet
      D.apply(s, {{ type: "d", tick: 6, players: {{ "0": [3, 2, 0, 1] }} }}).players,
      JSON.stringify(s) === before,                     // didn't change the old state
    ]));
    """
    out = json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                                    check=True).stdout)
    assert out == [None, None, [[3, 2, 0, 1]], True]


def test_messages_are_much_smaller():
    states, msgs = recorded("grand", ticks=600)
    full = sum(len(json.dumps(s, separators=(",", ":"))) for s in states)
    sent = sum(len(json.dumps(m, separators=(",", ":"))) for m in msgs)
    assert sent < full * 0.4


def test_keyframes_now_and_then():
    _, msgs = recorded("platform", ticks=200, keyframe_every=50)
    assert [k for k, m in enumerate(msgs) if m["type"] == "state"] == [0, 50, 100, 150]


def test_tricky_changes():
    a = {"type": "state", "tick": 1, "players": [[1, 2]], "level": [{"t": "rect", "r": [1], "c": "#fff"}],
         "walls": None, "crown": 2, "scores": [0, 0]}
    cases = [
        {**a, "tick": 2, "players": [[1, 2], [3, 4]]},                 # a list grows
        {**a, "tick": 2, "level": [{"t": "rect", "r": [1]}]},           # a shape loses a key
        {**a, "tick": 2, "level": [{"t": "rect", "r": [2], "c": "#fff"}]},  # a shape moves
        {**a, "tick": 2, "walls": [10, 20]},                            # None -> list
        {k: v for k, v in a.items() if k != "crown"} | {"tick": 2},     # a field goes away
        {**a, "tick": 2, "scores": [0, 1.0]},                           # int -> float
        {**a, "tick": 4, "events": [{"e": "go"}]},                      # skipped ticks
    ]
    for b in cases:
        d = delta.diff(a, b)
        b = {**b, "events": b.get("events", [])}
        assert delta.apply(roundtrip(a), roundtrip(d)) == b, d
    moved = delta.diff(a, cases[2])
    assert moved["level"] == {"0": {"r": [2]}}  # only what changed
    assert delta.diff(a, cases[4])["gone"] == ["crown"]
    assert delta.diff(a, cases[6])["base"] == 1 and "base" not in delta.diff(a, cases[0])
    # A list turning into a dict would read as a patch: send it whole instead
    assert delta.diff(a, {**a, "tick": 2, "scores": {"a": 1}}) is None
    with pytest.raises(ValueError):
        delta.apply(a, {"type": "d", "tick": 9})


class Inbox:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg):
        self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)


def test_players_get_their_own_speeds_and_late_arrivals_a_full_state():
    async def go():
        room = Room("ABCD")
        a = Inbox()
        await room.join("a", "Ann", a)
        room.settings.update(map="classic", bots=["bot:medium"])
        await room.start()
        await asyncio.sleep(0.3)
        late = Inbox()
        await room.join("w", "Wes", late)  # watches this match
        await asyncio.sleep(0.3)
        await room.stop()
        mine = [m for m in a.msgs if m["type"] in ("state", "d")]
        assert mine and all(len(m["you"]) == 3 for m in mine)
        assert all(len(p) == 4 for p in mine[0]["players"])
        seen = [m for m in late.msgs if m["type"] in ("state", "d")]
        assert seen[0]["type"] == "state" and seen[0]["events"] == []
        assert all("you" not in m for m in seen)
        rebuilt = rebuild(seen)
        assert rebuilt[-1]["tick"] == seen[-1]["tick"]
    asyncio.run(go())
