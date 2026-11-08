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
D, HR = [0, 0, 1, 0, 0], [0, 0, 0, 1, 1]
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


def server_run(map_name, inputs, place, others=None, power=None):
    """Run the real physics with player 0 pressing `inputs`. others(env)
    places the other ball (default: out of the way). power(match): sets up
    a power-up (the match has them on, with none turning up by themselves)."""
    m = Match(map_name, [{"kind": "human", "name": "a"}, {"kind": "human", "name": "b"}], 100,
              power_ups=power is not None)
    if power is not None:
        m.powerups.next_spawn = 10 ** 9
    m.set_phase("play")
    m.env.timer.limit = 0  # no sudden death
    me, other = m.env.players
    other.x, other.y = (150, 300) if map_name == "classic" else (210, 270)
    place(me)
    for _ in range(3):  # settle (land on the floor)
        m.tick()
    if others:
        others(m.env)
    if power:
        power(m)
        m.powerups.apply()
    state, you = m.snapshot(), player_motion(me)
    others_v = [None] + [[p.x_v, p.y_v] for p in m.env.players[1:]]
    steps = []
    for b in inputs:
        m.set_input(0, b)
        m.tick()
        steps.append((me.x, me.y))
    phys = m.physics()
    eff = m.powerups.effects[0] if m.powerups else None
    if eff:
        # (as js/net.js effectPhysics does)
        k = m.describe()["powerups"][eff[0]]
        phys = {**phys, "max_speed": phys["max_speed"] * k["max_speed"], "base": phys}
    return {"state": state, "you": you, "phys": phys, "inputs": inputs,
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
    "run holding heavy": ("platform", [HR] * 12, put(280, 270), None),
    # Up, down to land hard, up again as you land: a pogo bounce
    "pogo": ("platform", [U] + [NONE] * 4 + [D] * 8 + [U] * 10 + [NONE] * 10, put(340, 270), None),
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


def effect(kind, who=0, seconds=8):
    def power(m):
        m.powerups.effects[who] = [kind, seconds * 30]
    return power


def black_hole(m, wait=0):
    m.powerups.pending = (1, "hole")
    m.powerups.launch()
    m.powerups.hole["wait"] = wait


def opening_black_hole(m):
    black_hole(m, wait=5)  # (it starts pulling partway through)


POWER_CASES = {
    # A giant: twice the size, as much heavier as it is bigger
    "a giant runs": ("platform", [R] * 12, put(300, 260), None, effect("giant")),
    "a giant bumps a ball": ("platform", [R] * 12, put(260, 260), ball_coming(370, 279, 0), effect("giant")),
    "a ball bumps a giant": ("platform", [NONE] * 12, put(340, 260), ball_coming(240, 279, 14), effect("giant", 1)),
    # A ghost goes through
    "a ghost runs through a ball": ("platform", [R] * 12, put(260, 279), ball_coming(330, 279, 0), effect("ghost")),
    "a ball goes through a ghost": ("platform", [NONE] * 12, put(340, 279), ball_coming(260, 279, 14),
                                    effect("ghost", 1)),
    # Pulled by someone else's black hole
    "pulled by a black hole": ("platform", [NONE] * 15, put(300, 279), None, black_hole),
    "a black hole starts pulling": ("platform", [NONE] * 15, put(300, 279), None, opening_black_hole),
    "run at someone who's a black hole": ("platform", [R] * 10, put(300, 279), ball_coming(380, 279, 0), black_hole),
        "jump into a black hole": ("platform", [U] + [NONE] * 6, put(420, 279), None, black_hole),
}


@pytest.mark.parametrize("name", list(POWER_CASES))
def test_prediction_with_power_ups(name):
    map_name, inputs, place, others, power = POWER_CASES[name]
    case = server_run(map_name, inputs, place, others, power)
    predicted = run_predict([case])[0]
    for k, ((sx, sy), (px, py)) in enumerate(zip(case["steps"], predicted)):
        assert abs(px - sx) < 1.5 and abs(py - sy) < 1.5, (
            f"step {k + 1}: server ({sx:.1f}, {sy:.1f}) vs predicted ({px:.1f}, {py:.1f})")


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


# --- predicting frame after frame (physics.js predictor, used by js/net.js) ---
def run_frames(cases):
    """For each case, ask a predictor for a moment a bit further on each
    "frame" (fractional steps, as the browser does), with the buttons for
    later steps changing partway (you pressed something new): what it says,
    what predict() says from scratch, and how many steps each took."""
    script = f"""
    const P = require({json.dumps(str(PHYSICS))});
    const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
    const out = cases.map((c) => {{
      const pr = P.predictor(c.state, 0, c.you, c.phys, c.r, c.others);
      const rows = [];
      let stepsTaken = 0, stepsFresh = 0;
      for (let f = 0; f < 60; f++) {{
        const n = Math.min(0.3 + f * 0.27, c.steps.length);
        // Frames 0-19: the case's buttons; from frame 20 the ones for step 4
        // on change (as if you'd just pressed something else), and from
        // frame 40 the ones from step 2 on
        const buttons = (k) => f >= 40 && k >= 2 ? [0, 1, 0, 0, 0]
          : f >= 20 && k >= 4 ? [1, 0, 0, 0, 1] : c.inputs[Math.min(k, c.inputs.length - 1)];
        const before = pr.steps();
        const a = pr.at(n, buttons);
        stepsTaken += Math.max(0, pr.steps() - before);
        const inputs = [];
        for (let k = 0; k <= Math.ceil(n); k++) inputs.push(buttons(k));
        const b = P.predict(c.state, 0, c.you, c.phys, inputs, n, c.r, c.others);
        stepsFresh += Math.ceil(n);
        rows.push([a, b]);
      }}
      return {{ rows, stepsTaken, stepsFresh }};
    }});
    console.log(JSON.stringify(out));
    """
    res = subprocess.run([NODE, "-e", script], input=json.dumps(cases), capture_output=True,
                         text=True, check=True, cwd=ROOT)
    return json.loads(res.stdout)


def test_predicting_frame_after_frame_matches_predicting_from_scratch():
    """The predictor keeps stepping instead of replaying every frame, but
    must give exactly predict()'s answer, including when the buttons it
    guessed change, a ball's bumped, a part's moving or a black hole pulls."""
    picks = [CASES["run, then reverse"], CASES["bumped by another ball"], CASES["ride the sliding platform"],
             CASES["pogo"], CASES["fly on Classic"]]
    cases = [server_run(m, inputs, place, others) for m, inputs, place, others, *_ in picks]
    m, inputs, place, others, power = POWER_CASES["pulled by a black hole"]
    cases.append(server_run(m, inputs, place, others, power))
    for k, res in enumerate(run_frames(cases)):
        for f, (a, b) in enumerate(res["rows"]):
            assert a == b, f"case {k}, frame {f}: frame after frame {a} vs from scratch {b}"
        # (and far fewer steps than replaying everything each frame)
        assert res["stepsTaken"] < res["stepsFresh"] / 3, res


def test_a_predictor_asked_for_a_moment_before_its_state_says_where_the_state_has_you():
    """A state can arrive after the frame's timestamp was taken, so the
    browser can ask for a moment just before it (a negative number of
    steps): that's where the state has you, not a crash."""
    case = server_run(*CASES["run, then reverse"][:4])
    script = f"""
    const P = require({json.dumps(str(PHYSICS))});
    const c = JSON.parse(require("fs").readFileSync(0, "utf8"));
    const pr = P.predictor(c.state, 0, c.you, c.phys, c.r, c.others);
    const b = (k) => c.inputs[Math.min(k, c.inputs.length - 1)];
    console.log(JSON.stringify([pr.at(-0.4, b), pr.at(-3, b), pr.at(NaN, b), pr.at(1.5, b), pr.at(-0.2, b)]));
    """
    res = subprocess.run([NODE, "-e", script], input=json.dumps(case), capture_output=True,
                         text=True, check=True, cwd=ROOT)
    before, way_before, nan, later, again = json.loads(res.stdout)
    start = case["state"]["players"][0][:2]
    assert before == way_before == nan == again
    assert abs(before[0] - start[0]) < 1e-6 and abs(before[1] - start[1]) < 1e-6
    assert later != before  # (and it still predicts forwards after)
