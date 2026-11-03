// Client-side prediction for your own ball.
//
// The server is in charge of the game, so without this your ball only
// reacts once your keys have gone to the server and its new position has
// come back: a full round trip. Instead, the client takes the latest
// position the server sent and replays the keys you've pressed since
// (the ones the server hasn't used yet) through a small copy of the ball
// physics. That's drawn as your ball, so it reacts straight away.
//
// The copy covers what matters most for feel: input forces (divided by
// mass), gravity, the speed cap, jumping (with the same jump buffer and
// coyote time as bonk_game/envs/utils/player.py), and landing on, bouncing
// off and sliding on flat platform tops. It skips other players, slopes,
// bumpers and moving parts; when those matter the server's next position
// corrects it, and js/net.js smooths the correction out.
//
// Used by js/net.js in the browser and by tests in Node.
(function (root) {
  "use strict";

  const JUMP_BUFFER = 4;
  const COYOTE_TIME = 4;

  // Flat tops players can stand on, from the level shapes the server sends
  function floors(level, phys) {
    const out = [];
    for (const s of level) {
      if (s.t !== "rect" || s.k === "hazard") continue;
      const [x1, y1, x2, y2] = s.r;
      out.push({
        x1: Math.min(x1, x2), x2: Math.max(x1, x2), top: Math.min(y1, y2),
        e: s.e ?? phys.bounce, f: s.fr ?? 0,
      });
    }
    return out;
  }

  // One player's state from a server "state" message entry:
  // [x, y, heavy 0-1, alive, vx, vy, grounded]
  function fromServer(p, phys) {
    // p: [x, y, heavy, alive, vx, vy, standing] (js/net.js ownBall)
    const grounded = !!p[6];
    return {
      x: p[0], y: p[1], vx: p[4], vy: p[5],
      m: phys.min_m + p[2] * (phys.max_m - phys.min_m),
      grounded,
      jumpBuffer: 0,
      airSteps: grounded ? 0 : COYOTE_TIME + 1,
      jumpUsed: !grounded,
    };
  }

  function canJump(s, phys) {
    if (s.grounded && s.vy > -phys.jump_speed / 2) return true;
    return !s.jumpUsed && s.airSteps <= COYOTE_TIME;
  }

  function tryJump(s, phys) {
    if (s.jumpBuffer && canJump(s, phys)) {
      s.vy = Math.min(s.vy, -phys.jump_speed);
      s.grounded = false;
      s.jumpUsed = true;
      s.jumpBuffer = 0;
    }
  }

  // Advance one physics step with buttons b = [up, left, down, right, heavy].
  // Same order as the env: inputs, then collisions, then the update.
  function step(s, b, phys, fl, r) {
    const F = phys.force;
    // Inputs
    if (b[3]) s.vx += F / s.m;
    if (b[1]) s.vx -= F / s.m;
    if (b[2]) s.vy += F / s.m;
    if (b[0]) {
      if (phys.can_fly) s.vy -= F / s.m;
      else { s.jumpBuffer = JUMP_BUFFER; tryJump(s, phys); }
    }
    if (b[4] && s.m === phys.min_m) s.m = phys.max_m;

    // Collisions with flat tops. Checks the path since the last step too,
    // so a fast fall can't skip through a thin platform.
    s.grounded = false;
    const prevY = s.prevY ?? s.y;
    for (const f of fl) {
      if (s.x < f.x1 || s.x > f.x2) continue;
      const depth = s.y + r - f.top;
      if (depth < 0) continue;                          // above it
      if (s.y > f.top && prevY + r > f.top + 1) continue;  // was already below the top
      s.y -= depth;
      s.grounded = true;
      if (s.vy > 0) {
        s.vy = -f.e * s.vy;
        s.vx -= f.f * s.vx;
      }
    }

    // Update (player.update)
    if (!phys.can_fly) {
      if (s.grounded && s.vy > -phys.jump_speed / 2) { s.airSteps = 0; s.jumpUsed = false; }
      else s.airSteps += 1;
      if (s.jumpBuffer) { tryJump(s, phys); s.jumpBuffer = Math.max(0, s.jumpBuffer - 1); }
    }
    s.vy += phys.gravity;
    const v = phys.max_speed;
    s.vx = Math.max(-v, Math.min(v, s.vx));
    s.vy = Math.max(-v, Math.min(v, s.vy));
    s.prevY = s.y;
    s.x += s.vx;
    s.y += s.vy;
    if (phys.clamp_bottom != null) s.y = Math.min(phys.clamp_bottom - r, s.y);
    // pin_heavy: the Iron power-up keeps you at full weight
    if (phys.pin_heavy) s.m = phys.max_m;
    else if (s.m > phys.min_m) s.m = Math.max(s.m - phys.mass_decay, phys.min_m);
    return s;
  }

  // Where your ball will be `n` steps (can be fractional) after the server
  // state `p`, if the server applies buttons inputs[0], inputs[1], ...
  // Returns [x, y].
  function predict(p, phys, level, inputs, n, r) {
    const fl = floors(level, phys);
    let s = fromServer(p, phys);
    const whole = Math.floor(n);
    for (let k = 0; k < whole + 1; k++) {
      if (k === whole) {
        const frac = n - whole;
        if (frac <= 0) break;
        const next = step({ ...s }, inputs[Math.min(k, inputs.length - 1)] || [0, 0, 0, 0, 0], phys, fl, r);
        return [s.x + (next.x - s.x) * frac, s.y + (next.y - s.y) * frac];
      }
      s = step({ ...s }, inputs[Math.min(k, inputs.length - 1)] || [0, 0, 0, 0, 0], phys, fl, r);
    }
    return [s.x, s.y];
  }

  const api = { predict, step, fromServer, floors };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BonkPredict = api;
})(typeof window !== "undefined" ? window : globalThis);
