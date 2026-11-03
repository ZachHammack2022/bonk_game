// bonk web client: Network timing and predicting your own ball (with predict.js).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Network timing and predicting your own ball (see predict.js)
// ---------------------------------------------------------------------------
const net = {
  rtt: null,                                  // smoothed round trip, ms
  inputs: [{ t: 0, b: [0, 0, 0, 0, 0] }],     // when your buttons changed
};
setInterval(() => { if (app.ws && app.ws.readyState === WebSocket.OPEN) send({ type: "ping", t: performance.now() }); }, 1000);

function buttonsAt(t) {
  let b = net.inputs[0].b;
  for (const e of net.inputs) { if (e.t <= t) b = e.b; else break; }
  return b;
}

const own = { tick: null, base: null, offX: 0, offY: 0 };
// For tests and poking around in the console
const debug = (window.bonkDebug = { app, net, own, drawn: null, get fx() { return fx; } });

function predictFrom(entry, now) {
  const [arrived, S] = entry;
  const M = app.match;
  const i = M.slots.findIndex((s) => s.id === me.token);
  const tick = M.physics.tick_ms;
  const rtt = net.rtt ?? 0;
  // Steps from that state until the server uses the keys you're pressing
  // now (plus about half a step waiting for the next server step)
  const n = Math.min((now - arrived + rtt) / tick + 0.5, 15);
  const inputs = [];
  for (let k = 0; k <= Math.ceil(n); k++) inputs.push(buttonsAt(arrived - rtt + (k + 1) * tick));
  return BonkPredict.predict(ownBall(S, i), effectPhysics(M, S, i), S.level, inputs, n, M.radius);
}

// Your ball as predict.js wants it: [x, y, heavy, alive, vx, vy, standing].
// Everyone gets positions; only you get your speeds ("you").
function ownBall(S, i) {
  return [...S.players[i].slice(0, 4), ...(S.you || [0, 0, 0])];
}

// Your ball's physics with any power-up you're holding
function effectPhysics(M, S, i) {
  const eff = S.effects && S.effects[i];
  const k = eff && M.powerups && M.powerups[eff[0]];
  if (!k) return M.physics;
  const P = M.physics;
  const force = P.force * k.force * (k.pin_heavy ? P.max_m / P.min_m : 1);
  return { ...P, force, max_speed: P.max_speed * k.max_speed, gravity: P.gravity * k.gravity, pin_heavy: !!k.pin_heavy };
}

// Where to draw your ball: predicted, with corrections from the server
// faded in over ~0.1 s instead of snapping. Null when not predicting.
function ownPosition(now, dt) {
  const M = app.match;
  if (!PREDICT || !M || !app.states.length || typeof BonkPredict === "undefined" || replayer.active) return null;
  const i = M.slots.findIndex((s) => s.id === me.token);
  const entry = app.states[app.states.length - 1];
  const S = entry[1];
  if (i < 0 || S.phase !== "play" || !S.players[i][3] || (S.stand_ins || []).includes(i)) {
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
