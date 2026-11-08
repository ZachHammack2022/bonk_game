// bonk web client: Network timing and predicting your own ball (with physics.js).
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
// For tests and poking around in the console
const debug = (window.bonkDebug = { app, net, own, drawn: null, get fx() { return fx; } });

// A predictor (physics.js) for each of the last few server states: asked
// every frame, it only takes the steps it hasn't taken yet
const predictors = [];  // [[entry, predictor, slot]], newest last
function predictorFor(entry, i) {
  let found = predictors.find(([e, , slot]) => e === entry && slot === i);
  if (!found) {
    const S = entry[1], M = app.match;
    found = [entry, BonkPhysics.predictor(S, i, S.you || [0, 0, 0], effectPhysics(M, S, i), M.radius, othersMoving(S, M)), i];
    predictors.push(found);
    if (predictors.length > 3) predictors.shift();
  }
  return found[1];
}

function predictFrom(entry, now) {
  const arrived = entry[0];
  const M = app.match;
  const i = M.slots.findIndex((s) => s.id === me.id);
  const tick = M.physics.tick_ms;
  const rtt = net.rtt ?? 0;
  // Steps from that state until the server uses the keys you're pressing
  // now (plus about half a step waiting for the next server step)
  const n = Math.min((now - arrived + rtt) / tick + 0.5, 15);
  return predictorFor(entry, i).at(n, (k) => buttonsAt(arrived - rtt + (k + 1) * tick));
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
    return null;
  }
  const [x, y] = predictFrom(entry, now);
  if (own.tick !== S.tick) {
    if (own.base) {
      // The server moved us somewhere new (a respawn or new round): jump
      // there. Otherwise fade out the difference between the old and new
      // predictions, so a misprediction (say, a bot shoved us) doesn't snap.
      const was = own.base[1].players[i];
      const teleported = Math.hypot(S.players[i][0] - was[0], S.players[i][1] - was[1]) > MAX_JUMP * (S.tick - own.tick);
      if (teleported) { own.offX = own.offY = 0; }
      else {
        const [ox, oy] = predictFrom(own.base, now);
        own.offX += ox - x; own.offY += oy - y;
        playtest.correction(Math.hypot(ox - x, oy - y));
      }
    }
    own.tick = S.tick;
    own.base = entry;
  }
  const keep = Math.exp(-dt / 0.1);
  own.offX *= keep; own.offY *= keep;
  return [x + own.offX, y + own.offY];
}
