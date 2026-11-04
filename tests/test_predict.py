"""The browser's copy of the physics (static/physics.js, planck.js) against
the server's (envs/utils/world.py, Box2D): it should predict where your
ball goes, including when it meets other balls and the moving parts."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bonk_game.server.match import Match
from bonk_game.server.scene import player_motion

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parent.parent
PHYSICS = ROOT / "bonk_game" / "server" / "static" / "physics.js"
HAVE_PLANCK = (ROOT / "node_modules" / "planck").is_dir()
pytestmark = pytest.mark.skipif(NODE is None or not HAVE_PLANCK, reason="needs node and npm ci (planck)")

R, L, U, H = [0, 0, 0, 1, 0], [0, 1, 0, 0, 0], [1, 0, 0, 0, 0], [0, 0, 0, 0, 1]
NONE = [0, 0, 0, 0, 0]


def run_predict(cases):
    script = f"""
    const P = require({json.dumps(str(PHYSICS))});
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    const out = cases.map(c => c.steps.map((_, n) =>
      P.predict(c.state, 0, c.you, c.phys, c.inputs, n + 1, c.r, c.others)));
    console.log(JSON.stringify(out));
    """
    res = subprocess.run([NODE, "-e", script], input=json.dumps(cases), capture_output=True,
                         text=True, check=True, cwd=ROOT)
    return json.loads(res.stdout)


def server_run(map_name, inputs, place, others=None):
    """Run the real physics with player 0 pressing `inputs`. others(env)
    places the other ball (default: out of the way)."""
    m = Match(map_name, [{"kind": "human", "name": "a"}, {"kind": "human", "name": "b"}], 100)
    m.set_phase("play")
    m.env.timer.limit = 0  # no sudden death
    me, other = m.env.players
    other.x, other.y = (150, 300) if map_name == "classic" else (210, 270)
    place(me)
    for _ in range(3):  # settle (land on the floor)
        m.tick()
    if others:
        others(m.env)
    state, you = m.snapshot(), player_motion(me)
    others_v = [None] + [[p.x_v, p.y_v] for p in m.env.players[1:]]
    steps = []
    for b in inputs:
        m.set_input(0, b)
        m.tick()
        steps.append((me.x, me.y))
    return {"state": state, "you": you, "phys": m.physics(), "inputs": inputs,
            "r": me.r, "steps": steps, "others": others_v}


def put(x, y):
    def place(p):
        p.x, p.y, p.x_v, p.y_v = x, y, 0, 0
    return place


def ball_coming(x, y, vx):
    def others(env):
        b = env.players[1]
        b.x, b.y, b.x_v, b.y_v = x, y, vx, 0
    return others


def slider_moving(vx):
    def others(env):
        env.map.platform.vx = vx
    return others


CASES = {
    "run right on a platform": ("platform", [R] * 12, put(280, 270), None),
    "run, then reverse": ("platform", [R] * 6 + [L] * 8, put(340, 270), None),
    "jump and land": ("platform", [U] + [NONE] * 24, put(340, 270), None),
    "jump while running": ("platform", [R, U] + [R] * 10, put(280, 270), None),
    "jump and hover": ("platform", [U] * 30, put(340, 270), None),
    "hover on the way down": ("platform", [NONE] * 3 + [U] * 12, put(340, 150), None),
    "heavy then move": ("platform", [H] + [L] * 10, put(380, 270), None),
    # (Box2D and planck.js bounce a fast landing on a moving part a little
    # differently: within a few px, which js/net.js smooths out)
    "fall onto the slider": ("slider", [NONE] * 10, put(380, 220), None, 3),
    "fly on Classic": ("classic", [U] * 10 + [R] * 10, put(340, 300), None),
    # What the old hand-written prediction couldn't do
    "bumped by another ball": ("platform", [NONE] * 12, put(340, 279), ball_coming(260, 279, 14)),
    "run into another ball": ("platform", [R] * 12, put(260, 279), ball_coming(360, 279, 0)),
    "ride the sliding platform": ("slider", [NONE] * 15, put(340, 279), slider_moving(6)),
    "roll down a ramp": ("ramps", [NONE] * 15, put(200, 250), None),
}


@pytest.mark.parametrize("name", list(CASES))
def test_prediction_matches_the_server(name):
    map_name, inputs, place, others, *within = CASES[name]
    within = within[0] if within else 1.5
    case = server_run(map_name, inputs, place, others)
    predicted = run_predict([case])[0]
    for k, ((sx, sy), (px, py)) in enumerate(zip(case["steps"], predicted)):
        assert abs(px - sx) < within and abs(py - sy) < within, (
            f"step {k + 1}: server ({sx:.1f}, {sy:.1f}) vs predicted ({px:.1f}, {py:.1f})")


def test_the_page_serves_the_planck_js_the_tests_use():
    """static/vendor/planck.min.js is node_modules' copy (npm run vendor),
    with a gzipped twin the server sends to browsers that take gzip."""
    import gzip
    vendor = ROOT / "bonk_game" / "server" / "static" / "vendor"
    served = (vendor / "planck.min.js").read_bytes()
    assert served == (ROOT / "node_modules" / "planck" / "dist" / "planck.min.js").read_bytes()
    assert gzip.decompress((vendor / "planck.min.js.gz").read_bytes()) == served
    version = json.loads((ROOT / "package.json").read_text())["devDependencies"]["planck"]
    assert f"Planck.js v{version}".encode() in served[:400]
