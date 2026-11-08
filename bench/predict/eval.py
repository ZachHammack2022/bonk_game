"""How well does the browser guess where the other balls are? (js/net.js
otherPositions, physics.js drive.)

Plays real matches (hard bots in every seat, so the buttons keep changing
as people's do) and records every state. Then, from each state, as your
ball (slot 0) is drawn h steps ahead of it (h grows with your ping), it
compares where each ball near you is drawn with where the server really
has it at that moment, which is where your ball meets it:

    today      drawn where the server last had it, a little in the past
               (the newest state; the browser draws a bit behind even that)
    coasting   predicted, coasting at its speed (what your ball's
               prediction already assumed, without drawing it)
    buttons    predicted, keeping its last buttons (btn): what's drawn now

    exact      (not sent) buttons and everyone's exact speeds, to see what
               sending speeds as well would add

    python -m bench.predict.eval [--ticks 900] [--seeds 3]   # results.md: the last run

Distances in px, for balls within 9 ball sizes of yours (the ones drawn
predicted at all). "Today" flatters today a little: the browser draws a
bit behind the newest state, so it's further off than this.
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess

from bonk_game.server.match import Match

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PHYSICS = os.path.join(ROOT, "bonk_game", "server", "static", "physics.js")
SCENARIOS = (("platform", 4, False), ("classic", 4, False), ("grand", 8, True), ("ramps", 6, True), ("decks", 8, False))
# Steps ahead your ball is drawn: about (ping + time since the state came) / 33 ms + 0.5
HORIZONS = {"~60 ms ping": 3, "~120 ms ping": 5, "~200 ms ping": 7, "~300 ms ping": 10}


def record(map_name, n, pu, ticks, seed):
    m = Match(map_name, [{"kind": "bot:hard", "name": f"b{i}"} for i in range(n)], 1000,
              power_ups=pu, seed=seed)
    states = []
    while len(states) < ticks:
        m.tick()
        s = m.snapshot()
        if s["phase"] == "play":
            s["you"] = list(m.motion(0))
            s["vel"] = [list(m.motion(j))[:2] for j in range(n)]  # (not sent: to see what sending them would add)
            states.append(s)
        elif states:
            states.append(None)  # (a break in play: no predicting across it)
    desc = m.describe()
    return states, m.physics(), desc["radius"], desc.get("powerups")


SCRIPT = r"""
const P = require(process.argv[1]);
const { states, phys, r, powerups, horizons, near } = JSON.parse(require("fs").readFileSync(0, "utf8"));
const bits = (v) => [1, 2, 4, 8, 16].map((m) => (v & m ? 1 : 0));
// effectPhysics from js/net.js, for anyone's power-up
function eff(S, j) {
  const e = S.effects && S.effects[j];
  const k = e && powerups && powerups[e[0]];
  if (!k) return phys;
  const mult = k.force * (k.pin_heavy ? phys.max_m / phys.min_m : 1);
  return { ...phys, force: phys.force * mult, fly_force: (phys.fly_force ?? phys.force) * mult,
    max_speed: phys.max_speed * k.max_speed, gravity: phys.gravity * k.gravity, pin_heavy: !!k.pin_heavy, base: phys };
}
const out = {};
for (const [label, h] of Object.entries(horizons)) {
  const err = { today: [], coasting: [], buttons: [], exact: [] };
  for (let k = 1; k + h < states.length; k++) {
    const S = states[k], prev = states[k - 1];
    let ok = !!(S && prev);
    for (let q = 1; ok && q <= h; q++) ok = !!states[k + q];
    if (!ok || !S.players[0][3] || (S.held && S.held[0])) continue;
    const truth = states[k + h];
    const others = S.players.map((p, j) => (prev.players[j] && prev.players[j][3] && p[3]
      ? [p[0] - prev.players[j][0], p[1] - prev.players[j][1]] : null));
    const yours = (q) => bits(states[k + 1 + Math.min(q, h - 1)].btn[0]);  // (you know your own)
    const drive = S.btn.map((v, j) => (j === 0 ? null : { b: bits(v), ph: eff(S, j) }));
    const a = P.predictor(S, 0, S.you, eff(S, 0), r, others, null);
    const b = P.predictor(S, 0, S.you, eff(S, 0), r, others, drive);
    const c = P.predictor(S, 0, S.you, eff(S, 0), r, S.vel, drive);
    a.at(h, yours); b.at(h, yours); c.at(h, yours);
    const ca = a.everyone(h), cb = b.everyone(h), cc = c.everyone(h);
    const mine = truth.players[0];
    S.players.forEach((p, j) => {
      const t = truth.players[j];
      if (j === 0 || !p[3] || !t[3] || !ca[j] || !cb[j]) return;
      if (Math.hypot(t[0] - p[0], t[1] - p[1]) > 200) return;  // (a respawn)
      if (Math.hypot(t[0] - mine[0], t[1] - mine[1]) > near * r) return;  // (only balls near you)
      err.today.push(Math.hypot(p[0] - t[0], p[1] - t[1]));
      err.coasting.push(Math.hypot(ca[j][0] - t[0], ca[j][1] - t[1]));
      err.buttons.push(Math.hypot(cb[j][0] - t[0], cb[j][1] - t[1]));
      err.exact.push(Math.hypot(cc[j][0] - t[0], cc[j][1] - t[1]));
    });
  }
  out[label] = err;
}
console.log(JSON.stringify(out));
"""


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else float("nan")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--ticks", type=int, default=900)
    p.add_argument("--seeds", type=int, default=3)
    a = p.parse_args(argv)
    node = shutil.which("node")
    pooled = {label: {"today": [], "coasting": [], "buttons": [], "exact": []} for label in HORIZONS}
    radius = None
    for map_name, n, pu in SCENARIOS:
        for seed in range(a.seeds):
            states, phys, r, powerups = record(map_name, n, pu, a.ticks, seed)
            radius = r
            res = subprocess.run([node, "-e", SCRIPT, PHYSICS], input=json.dumps(
                {"states": states, "phys": phys, "r": r, "powerups": powerups, "horizons": HORIZONS, "near": 9}),
                capture_output=True, text=True, check=True, cwd=ROOT)
            for label, err in json.loads(res.stdout).items():
                for k, v in err.items():
                    pooled[label][k] += v
    print(f"How far a ball near yours (within 9 ball sizes) is drawn from where the server has it when your ball"
          f" is there; px (a ball's radius is {radius:g} px). {len(SCENARIOS)} maps x {a.seeds} matches of"
          f" {a.ticks} ticks, hard bots everywhere:\n")
    print("| your ping | balls measured | today (median / 90% / 99%) | coasting | with their buttons (now drawn)"
          " | buttons + exact speeds (if they were sent) |")
    print("|---|---|---|---|---|---|")
    for label, err in pooled.items():
        cell = lambda xs: f"{statistics.median(xs):.1f} / {pct(xs, 0.9):.1f} / {pct(xs, 0.99):.1f}"
        cells = " | ".join(cell(err[k]) for k in ("today", "coasting", "buttons", "exact"))
        print(f"| {label} | {len(err['today'])} | {cells} |")
    within = lambda xs, d: 100 * sum(1 for x in xs if x <= d) / len(xs)
    print("\nShare drawn within half a ball (where a bump looks right):\n")
    print("| your ping | today | coasting | with their buttons | + exact speeds |")
    print("|---|---|---|---|---|")
    for label, err in pooled.items():
        cells = " | ".join(f"{within(err[k], radius / 2):.0f}%" for k in ("today", "coasting", "buttons", "exact"))
        print(f"| {label} | {cells} |")


if __name__ == "__main__":
    main()
