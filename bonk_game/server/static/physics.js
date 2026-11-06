// The browser's copy of the physics, for predicting your own ball.
//
// The server is in charge of the game, so without this your ball only
// reacts once your keys have gone to the server and its new position has
// come back: a full round trip. Instead, the browser takes the latest state
// the server sent, builds the same Box2D world the server runs (planck.js is
// a JavaScript port of Box2D; the server uses Box2D itself: see
// envs/utils/world.py), and replays the keys you've pressed since (the ones
// the server hasn't used yet). That's drawn as your ball, so it reacts
// straight away.
//
// Everything is in it: the level, slopes, bumpers, the moving parts and the
// other balls (moving on as they were: the browser can't know their keys),
// so bumping into someone or riding the slider is predicted too. bonk's own
// rules on top of Box2D (grip, jumping, launch pads, the speed cap, heavy)
// are the same as world.py's and player.py's, in the same order. When the
// server's answer differs (someone changed direction), js/net.js smooths
// the correction out.
//
// Used by js/net.js in the browser and by tests in Node.
(function (root) {
  "use strict";

  const planck = root.planck || (typeof require === "function" ? require("planck") : null);
  const JUMP_BUFFER = 4;
  const COYOTE_TIME = 4;

  // --- the world ------------------------------------------------------------
  // A Box2D world for the match's level (phys.world, from World.describe()
  // on the server), with the moving parts where `parts` says they are.
  function build(phys) {
    const B = phys.box2d;
    const ppm = B.ppm;
    const u = {
      m: (px) => px / ppm,
      toV: (v) => v / ppm / B.step_seconds,
      fromV: (v) => v * ppm * B.step_seconds,
    };
    const world = new planck.World({ gravity: planck.Vec2(0, B.base_gravity / ppm / B.step_seconds ** 2) });
    // Bounce and friction per contact, as the server's _Contacts sets them
    world.on("begin-contact", (c) => {
      const a = c.getFixtureA().getUserData(), b = c.getFixtureB().getUserData();
      const aBall = !!(a && a.ball), bBall = !!(b && b.ball);
      if (aBall && bBall) { c.setRestitution(B.player_bounce); c.setFriction(0); }
      else if (aBall || bBall) {
        const s = aBall ? b : a;
        c.setRestitution(s.e);
        c.setFriction(s.f * B.friction_scale);
      }
    });
    const ground = world.createBody();
    for (const spec of phys.world.static) addPiece(ground, spec, u, B);
    const parts = phys.world.parts.map((d) => makePart(world, ground, d, u, B));
    return { world, parts, balls: [], u, B, phys };
  }

  function addPiece(body, spec, u, B) {
    const c = planck.Vec2(u.m(spec.c[0]), u.m(spec.c[1]));
    const shape = spec.s === "circle"
      ? new planck.Circle(c, u.m(spec.r))
      : new planck.Box(u.m(spec.h[0]), u.m(spec.h[1]), c, spec.a);
    body.createFixture({
      shape, density: 1, friction: spec.f * B.friction_scale, restitution: spec.e,
      isSensor: !!spec.k, userData: spec,
    });
  }

  function setMass(body, mass) {
    body.setMassData({ mass, center: planck.Vec2(0, 0), I: 0 });
  }

  function damping(perStep, B) { return -Math.log(perStep) / B.step_seconds; }

  // A moving part, as bodies.py makes it
  function makePart(world, ground, d, u, B) {
    const at = planck.Vec2(u.m(d.at[0]), u.m(d.at[1]));
    const part = { d, body: null };
    if (d.kind === "mover") {
      part.body = world.createBody({ type: "kinematic", position: at });
    } else {
      part.body = world.createBody({
        type: "dynamic", position: at, fixedRotation: true,
        gravityScale: d.kind === "slider" ? 0 : 1, linearDamping: damping(d.damping, B),
      });
    }
    for (const spec of d.pieces) addPiece(part.body, spec, u, B);
    if (d.kind === "slider") {
      setMass(part.body, d.mass);
      world.createJoint(new planck.PrismaticJoint({
        enableLimit: true, lowerTranslation: u.m(-d.travel - d.at[0]), upperTranslation: u.m(d.travel - d.at[0]),
      }, ground, part.body, at, planck.Vec2(1, 0)));
    } else if (d.kind === "swing") {
      setMass(part.body, d.mass);
      world.createJoint(new planck.DistanceJoint({ frequencyHz: 0, dampingRatio: 0 }, ground, part.body,
        planck.Vec2(u.m(d.pivot[0]), u.m(d.pivot[1])), at));
    }
    return part;
  }

  // Put a moving part where the server says it is: [x, y, vx, vy]
  function placePart(sim, part, s) {
    const { u } = sim;
    part.body.setTransform(planck.Vec2(u.m(s[0]), u.m(s[1])), 0);
    part.body.setLinearVelocity(planck.Vec2(u.toV(s[2]), u.toV(s[3])));
    part.vx = s[2]; part.vy = s[3];
  }

  // After each Box2D step: the parts' own limits (bodies.py after_substep)
  function partRules(sim, part, before) {
    const { u } = sim, d = part.d, body = part.body;
    const p = body.getPosition(), v = body.getLinearVelocity();
    if (d.kind === "slider") {
      const x = p.x * sim.B.ppm;
      let vx = u.fromV(v.x);
      if (Math.abs(x) >= d.travel - 0.05 && before * x > 0) vx = -before * d.end_bounce;
      vx = Math.max(-d.max_speed, Math.min(d.max_speed, vx));
      body.setLinearVelocity(planck.Vec2(u.toV(vx), 0));
      part.vx = vx;
    } else if (d.kind === "swing") {
      const x = p.x * sim.B.ppm - d.pivot[0], y = p.y * sim.B.ppm - d.pivot[1];
      const th = Math.atan2(x, y);
      const tx = Math.cos(th), ty = -Math.sin(th);
      const omega = (u.fromV(v.x) * tx + u.fromV(v.y) * ty) / d.length;
      if (Math.abs(omega) > d.max_omega) {
        const s = Math.sign(omega) * d.max_omega * d.length;
        body.setLinearVelocity(planck.Vec2(u.toV(s * tx), u.toV(s * ty)));
      }
    }
  }

  // --- balls ----------------------------------------------------------------
  // A ball from the server's state: p is [x, y, heavy 0-1, alive], and
  // motion [vx, vy, standing on something] (yours from the server; others'
  // worked out from the last two states)
  function makeBall(sim, p, motion, ph, r) {
    const { u, world } = sim;
    const grounded = !!motion[2];
    const b = {
      x: p[0], y: p[1], vx: motion[0], vy: motion[1],
      m: ph.min_m + p[2] * (ph.max_m - ph.min_m),
      ph, grounded,
      heavyHeld: false, runDir: 0,
      jumpBuffer: 0, airSteps: grounded ? 0 : COYOTE_TIME + 1, jumpUsed: !grounded,
      body: world.createBody({ type: "dynamic", position: planck.Vec2(u.m(p[0]), u.m(p[1])), fixedRotation: true, bullet: true }),
    };
    b.body.createFixture({ shape: new planck.Circle(u.m(r)), density: 1, friction: 0, restitution: 0, userData: { ball: b } });
    sim.balls.push(b);
    return b;
  }

  function canJump(s) {
    if (s.grounded && s.vy > -s.ph.jump_speed / 2) return true;
    return !s.jumpUsed && s.airSteps <= COYOTE_TIME;
  }

  // landing: how fast you just hit the ground (a jump on landing: rules());
  // it always can, and pogos (player.try_jump)
  function tryJump(s, landing) {
    if (s.jumpBuffer && (landing != null || canJump(s))) {
      const boost = (s.ph.pogo || 0) * Math.max(0, landing || 0);
      s.vy = Math.min(s.vy, -(s.ph.jump_speed + boost));
      s.grounded = false;
      s.jumpUsed = true;
      s.jumpBuffer = 0;
    }
  }

  // Buttons b = [up, left, down, right, heavy] (controls.apply_input)
  function applyInput(s, b) {
    const ph = s.ph;
    const ts = ph.time_scale ?? 1;
    const F = ph.force * ts;  // sideways and down (player.push)
    if (b[3]) s.vx += F / s.m;
    if (b[1]) s.vx -= F / s.m;
    s.runDir = (b[3] ? 1 : 0) - (b[1] ? 1 : 0);  // (player.run_dir: grip() grips less running)
    if (b[2]) s.vy += F / s.m;
    if (b[0]) {
      // Flying up is full thrust; on jump maps "up" jumps, and hovers in the
      // air (cancels ph.hover of gravity: player.move_up)
      if (ph.can_fly) s.vy -= (ph.fly_force ?? ph.force) * ts / s.m;
      else {
        if (!s.grounded && ph.hover) s.vy -= ph.hover * ph.gravity * ts / s.m;
        s.jumpBuffer = JUMP_BUFFER; tryJump(s);
      }
    }
    // Heavy while the button's held (player.make_heavy)
    if (b[4]) { s.m = ph.max_m; s.heavyHeld = true; }
  }

  // player.begin_step: jumping
  function beginStep(s) {
    if (s.ph.can_fly) return;
    if (s.grounded && s.vy > -s.ph.jump_speed / 2) { s.airSteps = 0; s.jumpUsed = false; }
    else s.airSteps += 1;
    if (s.jumpBuffer) tryJump(s);
  }

  // player.end_step: let go of heavy unless it was held (the Iron power-up
  // keeps you heavy), forget which way you ran, and a remembered "up" press
  // counts down. The other balls' buttons aren't known: they stay as heavy
  // as they were.
  function endStep(s) {
    const ph = s.ph;
    if (s.jumpBuffer) s.jumpBuffer -= 1;
    if (ph.pin_heavy) s.m = ph.max_m;
    else if (s.controlled && !s.heavyHeld) s.m = ph.min_m;
    s.heavyHeld = false;
    s.runDir = 0;
  }

  // Ball.push
  function push(sim, s) {
    const { u, B } = sim, body = s.body;
    body.setTransform(planck.Vec2(u.m(s.x), u.m(s.y)), 0);
    if (s.mass !== s.m) { setMass(body, s.m); s.mass = s.m; }
    body.setGravityScale(s.ph.gravity / B.base_gravity);
    body.setLinearVelocity(planck.Vec2(u.toV(s.vx), u.toV(s.vy)));
  }

  // The normal of a touching contact, from fixture A to B (world.contact_normal)
  function contactNormal(c) {
    const m = c.getManifold();
    if (m.type === 0) {
      const pa = c.getFixtureA().getBody().getWorldPoint(m.localPoint);
      const pb = c.getFixtureB().getBody().getWorldPoint(m.points[0].localPoint);
      const dx = pb.x - pa.x, dy = pb.y - pa.y, d = Math.hypot(dx, dy);
      return d > 1e-9 ? [dx / d, dy / d] : [0, -1];
    }
    return m.type === 2 ? [-m.localNormal.x, -m.localNormal.y] : [m.localNormal.x, m.localNormal.y];
  }

  // Ball.standing: on top of something solid?
  function standing(s) {
    const body = s.body;
    for (let e = body.getContactList(); e; e = e.next) {
      const c = e.contact;
      if (!c.isTouching()) continue;
      const mine = c.getFixtureA().getBody() === body;
      const other = (mine ? c.getFixtureB() : c.getFixtureA()).getUserData();
      if (!other || other.ball || other.k) continue;
      const n = contactNormal(c);
      if ((mine ? -n[1] : n[1]) < -0.5) return true;
    }
    return false;
  }

  // world.launch
  function launch(s, spec, partV, nx, ny) {
    const up = spec.u;
    if (up) {
      if (nx * up[0] + ny * up[1] <= 0.5) return;
      [nx, ny] = up;
    }
    const vn = (s.vx - partV[0]) * nx + (s.vy - partV[1]) * ny;
    if (vn < spec.l) { s.vx += (spec.l - vn) * nx; s.vy += (spec.l - vn) * ny; }
  }

  // world.grip: slide more and more slowly over what you stand on
  function grip(sim, s, spec, nx, ny, other, dt) {
    const { u, B } = sim;
    const tx = -ny, ty = nx;
    const sv = other.getLinearVelocity();
    const vt = (s.vx - u.fromV(sv.x)) * tx + (s.vy - u.fromV(sv.y)) * ty;
    // Running the way you're going, it grips less (world.GRIP_RUNNING)
    const g = s.runDir * tx * vt > 0 ? B.grip_running : B.grip;
    const dv = vt * (1 - Math.exp(-spec.f * g * dt));
    s.vx -= dv * tx; s.vy -= dv * ty;
    if (other.isDynamic()) {
      other.applyLinearImpulse(planck.Vec2(u.toV(dv * tx) * s.m, u.toV(dv * ty) * s.m), other.getWorldCenter(), true);
    }
  }

  // World._rules: after each Box2D step of dt seconds
  function rules(sim, s, dt) {
    const { u, B } = sim, body = s.body;
    const p = body.getPosition(), v = body.getLinearVelocity();
    s.x = p.x * B.ppm; s.y = p.y * B.ppm; s.vx = u.fromV(v.x); s.vy = u.fromV(v.y);
    s.grounded = false;
    let ground = null;
    for (let e = body.getContactList(); e; e = e.next) {
      const c = e.contact;
      if (!c.isTouching()) continue;
      const fa = c.getFixtureA(), fb = c.getFixtureB();
      const mine = fa.getBody() === body;
      const other = (mine ? fb : fa).getUserData();
      if (!other || other.ball || other.k) continue;
      let [nx, ny] = contactNormal(c);
      if (mine) { nx = -nx; ny = -ny; }
      const otherBody = (mine ? fb : fa).getBody();
      if (ny < -0.5) {
        s.grounded = true;
        if (!ground || other.f > ground[0].f) ground = [other, nx, ny, otherBody];
      }
      if (other.l != null) {
        const part = sim.parts.find((pt) => pt.body === otherBody);
        launch(s, other, part ? [part.vx || 0, part.vy || 0] : [0, 0], nx, ny);
      }
    }
    if (ground && ground[0].f && s.vy >= -B.lift_off) grip(sim, s, ...ground, dt);
    // "Up" pressed just before landing: jump the moment you land
    if (s.grounded && s.jumpBuffer && !s.ph.can_fly) tryJump(s, s.fall);
    const cap = s.ph.max_speed;
    s.vx = Math.max(-cap, Math.min(cap, s.vx));
    s.vy = Math.max(-cap, Math.min(cap, s.vy));
    if (s.ph.clamp_bottom != null) s.y = Math.min(s.ph.clamp_bottom - (s.r ?? 0), s.y);
    body.setLinearVelocity(planck.Vec2(u.toV(s.vx), u.toV(s.vy)));
    body.setTransform(planck.Vec2(u.m(s.x), u.m(s.y)), 0);
  }

  // One physics step (World.step): your buttons `b` go to `me`
  function step(sim, me, b) {
    applyInput(me, b);
    const ts = sim.phys.time_scale ?? 1;
    const n = sim.phys.substeps || 1;
    for (const s of sim.balls) push(sim, s);
    // Who's standing on something where they are now (a step of no time
    // brings the contacts up to date), for jumping
    sim.world.step(0, sim.B.velocity_iterations, sim.B.position_iterations);
    me.grounded = standing(me);
    beginStep(me);
    me.body.setLinearVelocity(planck.Vec2(sim.u.toV(me.vx), sim.u.toV(me.vy)));
    const dt = ts * sim.B.step_seconds / n;
    for (let k = 0; k < n; k++) {
      const before = sim.parts.map((pt) => pt.vx);
      for (const s of sim.balls) s.fall = s.vy;  // (for a pogo on landing)
      sim.world.step(dt, sim.B.velocity_iterations, sim.B.position_iterations);
      sim.parts.forEach((pt, j) => partRules(sim, pt, before[j]));
      for (const s of sim.balls) rules(sim, s, dt);
    }
    for (const s of sim.balls) endStep(s);
  }

  // --- predicting -------------------------------------------------------------
  // Where your ball will be `n` steps (can be fractional) after the server
  // state S, if the server applies buttons inputs[0], inputs[1], ...
  //   i: your slot; you: [vx, vy, standing] (your speeds, from the server);
  //   phys: the match's physics, with your power-up (js/net.js; the
  //         match's own, for everyone else, is phys.base if different);
  //   others: [vx, vy] per slot (null: not known), for the other balls.
  // Returns [x, y].
  function predict(S, i, you, phys, inputs, n, r, others) {
    const base = phys.base || phys;
    const sim = build(base);
    (S.parts || []).forEach((st, j) => { if (sim.parts[j]) placePart(sim, sim.parts[j], st); });
    let me = null;
    S.players.forEach((p, j) => {
      if (!p[3] || (S.held && S.held[j])) return;
      if (j === i) {
        me = makeBall(sim, p, you, phys, r);
        me.controlled = true;
      } else {
        const v = (others && others[j]) || [0, 0];
        makeBall(sim, p, [v[0], v[1], 0], base, r);
      }
    });
    for (const s of sim.balls) s.r = r;
    if (!me) return [S.players[i][0], S.players[i][1]];
    const whole = Math.floor(n);
    for (let k = 0; k < whole; k++) step(sim, me, inputs[Math.min(k, inputs.length - 1)] || [0, 0, 0, 0, 0]);
    const frac = n - whole;
    if (frac > 0) {
      const x = me.x, y = me.y;
      step(sim, me, inputs[Math.min(whole, inputs.length - 1)] || [0, 0, 0, 0, 0]);
      return [x + (me.x - x) * frac, y + (me.y - y) * frac];
    }
    return [me.x, me.y];
  }

  const api = { predict, build };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BonkPhysics = api;
})(typeof window !== "undefined" ? window : globalThis);
