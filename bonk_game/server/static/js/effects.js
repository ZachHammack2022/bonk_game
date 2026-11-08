// bonk web client: Sound, particles, banners, the knockout feed, and what happens on each game event.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Sound: tiny synthesized blips (M toggles)
// ---------------------------------------------------------------------------
const sound = {
  ctx: null,
  muted: profileStore.get().muted,
  unlock() {
    if (!this.ctx) {
      try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return; }
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
  },
  setMuted(m) {
    this.muted = m;
    profileStore.update((p) => ({ ...p, muted: m }));
  },
  toggle() {
    this.setMuted(!this.muted);
    toast(this.muted ? "Sound off" : "Sound on");
  },
  tone(freq, dur, type = "sine", vol = 0.15, slide = 0) {
    if (this.muted || !this.ctx || prefs.volume <= 0) return;
    vol *= prefs.volume;
    const t = this.ctx.currentTime;
    const o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq * slide), t + dur);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.ctx.destination);
    o.start(t);
    o.stop(t + dur);
  },
  play(name, strength = 1) {
    switch (name) {
      case "beep": return this.tone(520, 0.12, "square", 0.06);
      case "go": return this.tone(880, 0.25, "square", 0.07);
      case "hit": return this.tone(180 + 120 * strength, 0.08, "triangle", 0.18 * strength);
      case "death": return this.tone(300, 0.35, "sawtooth", 0.08, 0.3);
      case "point": return this.tone(660, 0.18, "sine", 0.12, 1.5);
      case "win": [523, 659, 784].forEach((f, i) => setTimeout(() => this.tone(f, 0.25, "triangle", 0.12), i * 120)); return;
      case "super": [392, 523, 659, 784, 1047].forEach((f, i) => setTimeout(() => this.tone(f, 0.3, "square", 0.06), i * 90)); return;
      case "bomb": return this.tone(1400, 0.9, "sine", 0.06, 0.25);  // a falling whistle
      case "boom":
        this.tone(90, 0.7, "sawtooth", 0.2, 0.4);
        return this.tone(55, 0.9, "square", 0.12, 0.5);
    }
  },
};
window.addEventListener("pointerdown", () => sound.unlock());
window.addEventListener("keydown", () => sound.unlock());

// ---------------------------------------------------------------------------
// Effects: particles, rings, screen shake, banners
// ---------------------------------------------------------------------------
// How many particles at once (phones and tablets draw fewer)
const MAX_PARTS = (() => {
  let coarse = false;
  try { coarse = matchMedia("(pointer: coarse)").matches; } catch (e) { /* old browser */ }
  return () => (coarse ? 240 : 700);
})();
const fx = {
  parts: [], rings: [], shake: 0, banner: null, note: null, emotes: [], feed: [], trails: {}, booms: [],
  reset() { this.parts = []; this.rings = []; this.shake = 0; this.banner = null; this.note = null; this.emotes = []; this.feed = []; this.trails = {}; this.booms = []; },
  // shape: how each particle is drawn (looks.js: drawPart)
  burst(x, y, color, n = 26, speed = 7, size = 4.5, life = 0.7, gravity = true, shape = null) {
    // Phones draw fewer: the oldest go first past the cap
    const cap = Math.round(MAX_PARTS() * (typeof quality === "undefined" ? 1 : quality.parts[quality.level]));
    if (this.parts.length + n > cap) this.parts.splice(0, this.parts.length + n - cap);
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, s = speed * (0.3 + Math.random() * 0.9);
      this.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - (gravity ? 2 : 0), color,
        size: size * (0.5 + Math.random() * 0.7), life, age: 0, gravity, shape });
    }
  },
  ring(x, y, color, life = 0.45) { this.rings.push({ x, y, color, life, age: 0 }); },
  kick(n) { if (prefs.shake) this.shake = Math.max(this.shake, n); },
  say(text, color, big = false) { this.banner = { text, color, big, at: performance.now() }; },
  // A smaller line under the main banner ("Green is out")
  tell(text, color) { this.note = { text, color, at: performance.now() }; },
  confetti(color) {
    for (let k = 0; k < 3; k++) {
      this.burst(150 + Math.random() * 380, 120 + Math.random() * 80, color, 25, 8, 4.5, 1.6);
      this.burst(150 + Math.random() * 380, 120 + Math.random() * 80, T.accent, 12, 7, 4.5, 1.6);
    }
  },
  update(dt) {
    const k = dt * 30;
    for (const p of this.parts) {
      p.age += dt;
      p.x += p.vx * k; p.y += p.vy * k;
      if (p.gravity) p.vy += 0.35 * k;
      p.vx *= 0.97 ** k;
    }
    this.parts = this.parts.filter((p) => p.age < p.life);
    for (const r of this.rings) r.age += dt;
    this.rings = this.rings.filter((r) => r.age < r.life);
    this.shake = Math.max(0, this.shake - dt * 40);
  },
};

// Knockout feed, top right: "Ann 💥 Bob", "Bob fell", newest at the bottom
const FEED_LINES = 4, FEED_TIME = 5000;

function drawFeed(now) {
  fx.feed = fx.feed.filter((f) => now - f.at < FEED_TIME);
  let y = 54;
  for (const f of fx.feed) {
    // Each line is drawn once (feedLine) and then copied, fading out
    if (!f.img || f.scale !== view.scale) feedLine(f);
    ctx.globalAlpha = clamp((FEED_TIME - (now - f.at)) / 600, 0, 1);
    ctx.drawImage(f.img, W - 10 - f.w, y - 12, f.w, 26);
    ctx.globalAlpha = 1;
    y += 24;
  }
}

// One line of the feed, into its own little canvas (f.img, f.w wide)
function feedLine(f) {
  const slots = app.match.slots;
  // Pieces drawn left to right: [text, colour, ball colour or null]
  const victim = slots[f.victim];
  const parts = [];
  if (f.power !== undefined) {
    const k = app.match.powerups && app.match.powerups[f.power];
    parts.push([slotName(f.who), T.text, slots[f.who].color], [`${POWER_ICONS[f.power]} ${k ? k.title : f.power}`, POWER_COLORS[f.power], null]);
  } else if (f.by !== null && slots[f.by]) {
    parts.push([slotName(f.by), T.text, slots[f.by].color], ["💥", T.text, null], [slotName(f.victim), T.text, victim.color]);
  } else {
    parts.push([slotName(f.victim), T.text, victim.color], [f.wall ? "got squished" : "fell", T.dim, null]);
  }
  const main = ctx;
  const c = f.img || document.createElement("canvas");
  try {
    ctx = c.getContext("2d");
    ctx.font = `600 12px ${T.font}`;
    const widths = parts.map(([str, , ball]) => ctx.measureText(str).width + (ball ? 14 : 0));
    const w = Math.ceil(widths.reduce((a, b) => a + b, 0) + 6 * (parts.length - 1) + 20);
    c.width = Math.ceil(w * view.scale); c.height = Math.ceil(26 * view.scale);  // (the pill and its shadow)
    ctx.setTransform(view.scale, 0, 0, view.scale, 0, 0);
    pill(0, 2, w, 20, 0.6);
    let x = 10;
    parts.forEach(([str, color, ball], k) => {
      if (ball) { circle(x + 5, 12, 5, ball); x += 14; }
      text(str, 12, color, x, 12, { align: "left", weight: 700, shadow: false });
      x += widths[k] - (ball ? 14 : 0) + 6;
    });
    f.w = w;
  } finally {
    ctx = main;
  }
  f.img = c; f.scale = view.scale;
}

function isMe(i) {
  const s = app.match && app.match.slots[i];
  return !!s && s.id === me.id;
}

function slotName(i) {
  const s = app.match && app.match.slots[i];
  if (!s) return "?";
  return s.id === me.id ? "You" : s.name;
}

function onEvent(ev, state) {
  const slots = app.match ? app.match.slots : [];
  switch (ev.e) {
    case "beep": sound.play("beep"); haptics.tick(); break;
    case "go": sound.play("go"); fx.say("GO!", T.accent, true); haptics.buzz("hit"); break;
    case "death": {
      const c = slots[ev.i] ? slots[ev.i].color : T.text;
      let x = clamp(ev.x, 12, W - 12), y = clamp(ev.y, 12, H - 12);
      // Your own ball was drawn ahead of the server (prediction): burst where you saw it
      if (slots[ev.i] && slots[ev.i].id === me.id && debug.drawn && performance.now() - debug.drawn.t < 200) {
        x = clamp(debug.drawn.x, 12, W - 12); y = clamp(debug.drawn.y, 12, H - 12);
      }
      knockoutEffect(x, y, c, slots[ev.i] && slots[ev.i].ko);
      if (isMe(ev.i)) haptics.buzz([60, 40, 90]);       // you're out
      else if (isMe(ev.by)) haptics.buzz([15, 50, 25]); // you got them
      fx.kick(10);
      sound.play("death");
      fx.feed.push({ victim: ev.i, by: ev.by ?? null, wall: !!ev.wall, at: performance.now() });
      if (fx.feed.length > FEED_LINES) fx.feed.shift();
      const eliminated = (state.events || []).some((e) => e.e === "eliminated" && e.i === ev.i);
      if (app.match && !app.match.reset_round_on_kill) {
        // Where they respawn (unless that was their last life)
        const p = state.players[ev.i];
        if (!eliminated) fx.ring(p[0], p[1], c);
      } else if (app.match && !(state.events || []).some((e) => e.e === "round")) {
        // Knocked out but the round goes on
        const name = slotName(ev.i);
        fx.tell(name === "You" ? "You're out!" : `${name} is out`, c);
      }
      break;
    }
    case "score": {
      sound.play("point");
      const M = app.match;
      if (ev.team !== undefined) {
        const mine = M.slots.find((x) => x.id === me.id);
        const ours = mine && mine.team === ev.team;
        fx.say(`${M.team_names[ev.team]} scores!`, M.team_colors[ev.team]);
        if (mine) fx.tell(ours ? "Nice!" : "Ouch", ours ? T.accent : T.dim);
        break;
      }
      const c = slots[ev.i] ? slots[ev.i].color : T.text;
      const name = slotName(ev.i);
      if (M && M.reset_round_on_kill) fx.say(name === "You" ? "You score!" : `${name} scores!`, c);
      else fx.say(`+1 ${name}`, c);
      break;
    }
    case "eliminated": {
      const c = slots[ev.i] ? slots[ev.i].color : T.text;
      const name = slotName(ev.i);
      fx.tell(name === "You" ? "You're out of lives!" : `${name} is out of lives`, c);
      break;
    }
    case "crown": {
      const c = slots[ev.i] ? slots[ev.i].color : T.text;
      const name = slotName(ev.i);
      // Only call it out when it's about you; the feed shows the rest
      if (name === "You") fx.tell("You've got the crown!", c);
      else if (isMe(ev.from)) fx.tell(`${name} stole your crown!`, c);
      sound.play("point");
      break;
    }
    case "spawn":
      fx.ring(ev.x, ev.y, POWER_COLORS[ev.k] || T.accent, 0.5);
      break;
    case "pickup": {
      const k = app.match.powerups && app.match.powerups[ev.k];
      fx.burst(ev.x, ev.y, POWER_COLORS[ev.k] || T.accent, 16, 5, 3.5, 0.5, false);
      sound.play("point");
      if (isMe(ev.i)) { fx.tell(`${POWER_ICONS[ev.k]} ${k ? k.title : ev.k}!`, POWER_COLORS[ev.k]); haptics.buzz("tap"); }
      fx.feed.push({ power: ev.k, who: ev.i, at: performance.now() });
      if (fx.feed.length > FEED_LINES) fx.feed.shift();
      break;
    }
    case "super":
      startSuperScene(ev.i);
      if (isMe(ev.i)) haptics.buzz([20, 40, 20, 40, 80]);
      sound.play("super");
      break;
    case "bomb": sound.play("bomb"); break;
    case "boom": {
      const k = app.match.powerups && app.match.powerups.plane;
      boomEffect(ev.x, ev.y, k ? k.blast : 85);
      haptics.buzz(nearMe(ev.x, ev.y, (k ? k.blast : 85) * 2) ? "big" : "hit");
      sound.play("boom");
      break;
    }
    case "swap": {
      // A puff where each of them was, and a ring where each of them is now
      const ci = slots[ev.i] ? slots[ev.i].color : T.text, cj = slots[ev.j] ? slots[ev.j].color : T.text;
      fx.burst(ev.a[0], ev.a[1], POWER_COLORS.swap, 18, 5, 4, 0.5, false);
      fx.burst(ev.b[0], ev.b[1], POWER_COLORS.swap, 18, 5, 4, 0.5, false);
      fx.ring(ev.b[0], ev.b[1], ci); fx.ring(ev.a[0], ev.a[1], cj);
      sound.tone(500, 0.18, "triangle", 0.1, 2); sound.tone(1000, 0.18, "triangle", 0.08, 0.5);
      if (isMe(ev.j)) fx.tell(`${slotName(ev.i)} swapped with you!`, ci);
      if (isMe(ev.i) || isMe(ev.j)) haptics.buzz("hit");
      break;
    }
    case "pop": {
      const c = slots[ev.i] ? slots[ev.i].color : T.text;
      fx.burst(clamp(ev.x, 12, W - 12), clamp(ev.y, 12, H - 12), c, ev.end ? 10 : 18, ev.end ? 3 : 6, 3.5, 0.45, !ev.end);
      if (!ev.end) sound.tone(700, 0.12, "sine", 0.06, 0.5);
      break;
    }
    case "hole_on":
      // It starts pulling
      fx.ring(ev.x, ev.y, POWER_COLORS.hole, 0.6);
      fx.kick(8);
      sound.tone(70, 1.2, "sawtooth", 0.12, 0.6);
      break;
    case "gulp": {
      // Swallowed: a swirl of their colour into the hole
      const c = slots[ev.j] ? slots[ev.j].color : T.text;
      fx.burst(ev.x, ev.y, c, 22, 4, 4, 0.5, false);
      sound.tone(500, 0.35, "sine", 0.12, 0.2);
      break;
    }
    case "hole_end":
      fx.ring(ev.x, ev.y, POWER_COLORS.hole, 0.5);
      fx.burst(ev.x, ev.y, POWER_COLORS.hole, 24, 6, 4, 0.6, false);
      sound.tone(200, 0.4, "sine", 0.1, 3);
      break;
    case "land": {
      const c = slots[ev.i] ? slots[ev.i].color : T.text;
      fx.ring(ev.x, ev.y, c);
      break;
    }
    case "punch":
      if (nearMe(ev.x, ev.y, 60)) haptics.buzz("big");
      fx.burst(ev.x, ev.y, POWER_COLORS.punch, 30, 10, 4.5, 0.6);
      fx.ring(ev.x, ev.y, POWER_COLORS.punch, 0.4);
      fx.kick(12);
      sound.play("hit", 1);
      break;
    case "overtime": fx.say("Overtime!", T.accent); fx.tell("Next knockout wins", T.text); sound.play("go"); break;
    case "sudden": fx.say("Sudden death!", T.danger); fx.kick(6); sound.play("go"); break;
    case "hit":
      critterHit(ev.x, ev.y, ev.s);
      // (Only real bumps: rolling against someone isn't worth a buzz)
      if (ev.s >= 7 && (isMe(ev.by) || nearMe(ev.x, ev.y))) haptics.buzz("bump", ev.s / 18);
      fx.burst(ev.x, ev.y, "#ffd23f", Math.round(3 + ev.s * 0.6), ev.s * 0.5, 3.5, 0.4, false, "star");
      fx.kick(Math.min(8, ev.s * 0.4));
      sound.play("hit", Math.min(1, ev.s / 18));
      break;
    case "over": sound.play("win"); break;
  }
}
