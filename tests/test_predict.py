"""The browser's prediction of your own ball (static/predict.js) against
the real physics: with nothing else around, it should match the server."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bonk_game.server.match import Match
from bonk_game.server.scene import level_shapes, player_state

NODE = shutil.which("node")
PREDICT = Path(__file__).resolve().parent.parent / "bonk_game" / "server" / "static" / "predict.js"
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")

R, L, U, H = [0, 0, 0, 1, 0], [0, 1, 0, 0, 0], [1, 0, 0, 0, 0], [0, 0, 0, 0, 1]
NONE = [0, 0, 0, 0, 0]


def run_predict(cases):
    script = f"""
    const P = require({json.dumps(str(PREDICT))});
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    const out = cases.map(c => c.steps.map((_, n) =>
      P.predict(c.start, c.phys, c.level, c.inputs, n + 1, c.r)));
    console.log(JSON.stringify(out));
    """
    res = subprocess.run([NODE, "-e", script], input=json.dumps(cases), capture_output=True,
                         text=True, check=True)
    return json.loads(res.stdout)


def server_run(map_name, inputs, place):
    """Run the real physics with player 0 pressing `inputs`, player 1 far away."""
    m = Match(map_name, [{"kind": "human", "name": "a"}, {"kind": "human", "name": "b"}], 100)
    m.set_phase("play")
    m.env.timer.limit = 0  # no sudden death
    me, other = m.env.players
    # The other ball sits out of the way (on the platform's far end, so it
    # doesn't fall off and restart the round)
    other.x, other.y = (150, 300) if map_name == "classic" else (210, 270)
    place(me)
    for _ in range(3):  # settle (land on the floor)
        m.tick()
    start = player_state(me)
    level = level_shapes(m.env.map)
    steps = []
    for b in inputs:
        m.set_input(0, b)
        m.tick()
        steps.append((me.x, me.y))
    return {"start": start, "phys": m.physics(), "level": level, "inputs": inputs,
            "r": me.r, "steps": steps}


def put(x, y):
    def place(p):
        p.x, p.y, p.x_v, p.y_v = x, y, 0, 0
    return place


CASES = {
    "run right on a platform": ("platform", [R] * 12, put(280, 270)),
    "run, then reverse": ("platform", [R] * 6 + [L] * 8, put(340, 270)),
    "jump and land": ("platform", [U] + [NONE] * 24, put(340, 270)),
    "jump while running": ("platform", [R, U] + [R] * 10, put(280, 270)),
    "heavy then move": ("platform", [H] + [L] * 10, put(380, 270)),
    "fall onto the slider": ("slider", [NONE] * 10, put(380, 220)),
    "fly on Classic": ("classic", [U] * 10 + [R] * 10, put(340, 300)),
}


@pytest.mark.parametrize("name", list(CASES))
def test_prediction_matches_the_server(name):
    map_name, inputs, place = CASES[name]
    case = server_run(map_name, inputs, place)
    predicted = run_predict([case])[0]
    for k, ((sx, sy), (px, py)) in enumerate(zip(case["steps"], predicted)):
        assert abs(px - sx) < 1.5 and abs(py - sy) < 1.5, (
            f"step {k + 1}: server ({sx:.1f}, {sy:.1f}) vs predicted ({px:.1f}, {py:.1f})")
