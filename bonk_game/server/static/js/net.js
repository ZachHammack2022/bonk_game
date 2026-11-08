// bonk web client: Network timing, and predicting your own ball and the
// ones near it (with physics.js).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Network timing and predicting your own ball (see physics.js)
// ---------------------------------------------------------------------------
const net = {
  rtt: null,                                  // smoothed round trip, ms
  inputs: [{ t: 0, b: [0, 0, 0, 0, 0] }],     // when your buttons changed
};
// A ping a second; it carries your current round trip, so the server can
// show how laggy players are where (the /admin page)
setInterval(() => {
  if (app.ws && app.ws.readyState === WebSocket.OPEN) {
    send({ type: "ping", t: performance.now(), ...(net.rtt == null ? {} : { rtt: Math.round(net.rtt) }) });
  }
}, 1000);

function buttonsAt(t) {
  let b = net.inputs[0].b;
  for (const e of net.inputs) { if (e.t <= t) b = e.b; else break; }
  return b;
}

const own = { tick: null, base: null, offX: 0, offY: 0 };
// The other balls, predicted alongside yours (otherPositions): per slot,
// the fading correction [dx, dy] and how much to draw it predicted (0-1)
const near = { off: [], w: [], at: null };
// For tests and poking around in the console
const debug = (window.bonkDebug = { app, net, own, near, drawn: null, get fx() { return fx; } });

// A predictor (physics.js) for each of the last few server states: asked
// every frame, it only takes the steps it hasn't taken yet
const predictors = [];  // [[entry, predictor, slot]], newest last
function predictorFor(entry, i) {
  let found = predictors.find(([e, , slot]) => e === entry && slot === i);
  if (!found) {
    const S = entry[1], M = app.match;
    found = [entry, BonkPhysics.predictor(S, i, S.you || [0, 0, 0], effectPhysics(M, S, i), M.radius,
      othersMoving(S, M), othersDriving(S, M, i)), i];
    predictors.push(found);
    if (predictors.length > 3) predictors.shift();
  }
  return found[1];
}

// Steps from a state until the server uses the keys you're pressing now
// (plus about half a step waiting for the next server step): how far ahead
// your ball, and the balls near it, are drawn
function stepsAhead(entry, now) {
  const rtt = net.rtt ?? 0;
  return Math.min((now - entry[0] + rtt) / app.match.physics.tick_ms + 0.5, MAX_AHEAD);
}
const MAX_AHEAD = 15;

// Where your ball will be then: [x, y], and everyone else at that moment
// (.all: by slot, [x, y], from physics.js predictor.everyone)
function predictFrom(entry, now) {
  const arrived = entry[0];
  const M = app.match;
  const i = M.slots.findIndex((s) => s.id === me.id);
  const tick = M.physics.tick_ms;
  const rtt = net.rtt ?? 0;
  const n = stepsAhead(entry, now);
  const pr = predictorFor(entry, i);
  const at = pr.at(n, (k) => buttonsAt(arrived - rtt + (k + 1) * tick));
  at.all = pr.everyone(n);
  return at;
}

// The other balls' buttons from the state (btn: what each moved with last
// step), so the prediction has them keep pressing those instead of just
// coasting; each with their own power-up. Null to have them coast (an older
// server, or turned off).
const BUTTON_BITS = [1, 2, 4, 8, 16];  // up, left, down, right, heavy
const drivingCache = new WeakMap();
function othersDriving(S, M, i) {
  if (!S.btn || !predictOthers()) return null;
  let d = drivingCache.get(S);
  if (!d) {
    d = S.btn.map((v, j) => (j === i ? null : { b: BUTTON_BITS.map((m) => (v & m ? 1 : 0)), ph: effectPhysics(M, S, j) }));
    drivingCache.set(S, d);
  }
  return d;
}

// Drawing nearby balls predicted (Settings; ?predict_others=0 turns it off)
function predictOthers() {
  return PREDICT_OTHERS && prefs.predictOthers !== false;
}

// How fast everyone else is going (px per physics step), worked out from
// this state and the one before: only your own speeds are sent ("you").
// Remembered for each state, as it's asked for every frame.
const movingCache = new WeakMap();
function othersMoving(S, M) {
  if (movingCache.has(S)) return movingCache.get(S);
  let prev = null;
  for (let k = app.states.length - 1; k >= 0; k--) {
    const P = app.states[k][1];
    if (P.tick < S.tick) { prev = P; break; }
  }
  const ticks = prev ? S.tick - prev.tick : 0;
  const per = (M.physics.time_scale || 1) * ticks;
  const moving = S.players.map((p, j) => {
    const q = prev && prev.players[j];
    if (!q || !per || ticks > 3 || !q[3] || !p[3]) return null;
    return [(p[0] - q[0]) / per, (p[1] - q[1]) / per];
  });
  movingCache.set(S, moving);
  return moving;
}

// Your ball's physics with any power-up you're holding
function effectPhysics(M, S, i) {
  const eff = S.effects && S.effects[i];
  const k = eff && M.powerups && M.powerups[eff[0]];
  if (!k) return M.physics;
  const P = M.physics;
  const mult = k.force * (k.pin_heavy ? P.max_m / P.min_m : 1);
  const force = P.force * mult;
  return {
    ...P, force, fly_force: (P.fly_force ?? P.force) * mult, max_speed: P.max_speed * k.max_speed, gravity: P.gravity * k.gravity, pin_heavy: !!k.pin_heavy,
    base: P,  // (everyone else's)
  };
}

// Where to draw your ball: predicted, with corrections from the server
// faded in over ~0.1 s instead of snapping. Null when not predicting.
function ownPosition(now, dt) {
  const M = app.match;
  if (!PREDICT || !M || !app.states.length || typeof BonkPhysics === "undefined" || replayer.active) return null;
  const i = M.slots.findIndex((s) => s.id === me.id);
  const entry = app.states[app.states.length - 1];
  const S = entry[1];
  // (Held after a respawn: you're not moving, so there's nothing to predict)
  if (i < 0 || S.phase !== "play" || !S.players[i][3] || (S.held && S.held[i]) || (S.stand_ins || []).includes(i)) {
    // (Forget the last prediction too: when you're back, start afresh
    // rather than fading in from where you were before)
    own.tick = null; own.base = null; own.offX = own.offY = 0;
    near.at = null; near.off = []; near.w = [];
    return null;
  }
  const now_ = predictFrom(entry, now);
  const [x, y] = now_;
  near.at = now_.all;
  if (own.tick !== S.tick) {
    if (own.base) {
      // The server moved us somewhere new (a respawn or new round): jump
      // there. Otherwise fade out the difference between the old and new
      // predictions, so a misprediction (say, a bot shoved us) doesn't snap.
      const was = own.base[1].players[i];
      const teleported = Math.hypot(S.players[i][0] - was[0], S.players[i][1] - was[1]) > MAX_JUMP * (S.tick - own.tick);
      if (teleported) { own.offX = own.offY = 0; }
      else {
        const old = predictFrom(own.base, now);
        const [ox, oy] = old;
        own.offX += ox - x; own.offY += oy - y;
        playtest.correction(Math.hypot(ox - x, oy - y));
        // The same for the balls near you: where the last state had them
        // now, against where this one does
        now_.all.forEach((p, j) => {
          const o = old.all[j], off = near.off[j];
          if (!o || !p || Math.hypot(o[0] - p[0], o[1] - p[1]) > MAX_JUMP) { near.off[j] = null; return; }
          near.off[j] = [(off ? off[0] : 0) + o[0] - p[0], (off ? off[1] : 0) + o[1] - p[1]];
        });
      }
    }
    own.tick = S.tick;
    own.base = entry;
  }
  const keep = Math.exp(-dt / 0.1);
  own.offX *= keep; own.offY *= keep;
  for (const off of near.off) if (off) { off[0] *= keep; off[1] *= keep; }
  return [x + own.offX, y + own.offY];
}

// The other balls, after ownPosition: each drawn where it's predicted to be
// at the same moment as yours, so what you see bump you is what your ball
// bumps. Only near you: far away it's drawn where the server last had it
// (a little in the past, but never wrong), blending in between. Less so the
// further ahead it's guessing (a high ping), as their buttons may change.
//   players: the state being drawn (blended between server states);
//   mine: your slot; at: where your ball's drawn. Returns the new players.
const NEAR_FROM = 4, NEAR_TO = 9;  // ball sizes: fully predicted within, not at all beyond
const AHEAD_JUMP = 200;  // px between drawn and predicted: a respawn, not motion (don't blend)
function otherPositions(players, mine, at, dt, now) {
  const all = near.at;
  if (!all || !predictOthers() || !own.base) return players;
  const R = app.match.radius;
  const n = stepsAhead(own.base, now);
  const sure = clamp((MAX_AHEAD - n) / (MAX_AHEAD - 8), 0, 1);  // (from about 270 ms ahead, less)
  const ease = 1 - Math.exp(-dt / 0.15);
  return players.map((p, j) => {
    if (j === mine) return p;
    const q = all[j], off = near.off[j];
    const live = q && p[3] && Math.hypot(q[0] - p[0], q[1] - p[1]) < AHEAD_JUMP;
    const d = live ? Math.hypot(q[0] - at[0], q[1] - at[1]) / R : Infinity;
    const want = live ? clamp((NEAR_TO - d) / (NEAR_TO - NEAR_FROM), 0, 1) * sure : 0;
    const w = (near.w[j] = (near.w[j] || 0) + (want - (near.w[j] || 0)) * ease);
    if (!live || w < 0.001) return p;
    const x = q[0] + (off ? off[0] : 0), y = q[1] + (off ? off[1] : 0);
    return [p[0] + (x - p[0]) * w, p[1] + (y - p[1]) * w, p[2], p[3]];
  });
}
