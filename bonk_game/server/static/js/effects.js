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
    }
  },
};
window.addEventListener("pointerdown", () => sound.unlock());
window.addEventListener("keydown", () => sound.unlock());

// ---------------------------------------------------------------------------
// Effects: particles, rings, screen shake, banners
// ---------------------------------------------------------------------------
const fx = {
  parts: [], rings: [], shake: 0, banner: null, note: null, emotes: [], feed: [], trails: {},
  reset() { this.parts = []; this.rings = []; this.shake = 0; this.banner = null; this.note = null; this.emotes = []; this.feed = []; this.trails = {}; },
  // shape: how each particle is drawn (looks.js: drawPart)
  burst(x, y, color, n = 26, speed = 7, size = 4.5, life = 0.7, gravity = true, shape = null) {
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
  const slots = app.match.slots;
  let y = 54;
  ctx.font = "700 12px ui-rounded, system-ui, sans-serif";
  for (const f of fx.feed) {
    const alpha = clamp((FEED_TIME - (now - f.at)) / 600, 0, 1);
    // Pieces drawn right to left: [text, colour, ball colour or null]
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
    const widths = parts.map(([str, , ball]) => ctx.measureText(str).width + (ball ? 14 : 0));
    const w = widths.reduce((a, b) => a + b, 0) + 6 * (parts.length - 1) + 20;
    ctx.globalAlpha = alpha;
    pill(W - 10 - w, y - 10, w, 20, 0.6);
    let x = W - 10 - w + 10;
    parts.forEach(([str, color, ball], k) => {
      if (ball) { circle(x + 5, y, 5, ball); x += 14; }
      text(str, 12, color, x, y, { align: "left", weight: 700, shadow: false, alpha });
      x += widths[k] - (ball ? 14 : 0) + 6;
    });
    ctx.globalAlpha = 1;
    y += 24;
  }
}

function isMe(i) {
  const s = app.match && app.match.slots[i];
  return !!s && s.id === me.token;
}

function slotName(i) {
  const s = app.match && app.match.slots[i];
  if (!s) return "?";
  return s.id === me.token ? "You" : s.name;
}

function onEvent(ev, state) {
  const slots = app.match ? app.match.slots : [];
  switch (ev.e) {
    case "beep": sound.play("beep"); break;
    case "go": sound.play("go"); fx.say("GO!", T.accent, true); break;
    case "death": {
      const c = slots[ev.i] ? slots[ev.i].color : T.text;
      let x = clamp(ev.x, 12, W - 12), y = clamp(ev.y, 12, H - 12);
      // Your own ball was drawn ahead of the server (prediction): burst where you saw it
      if (slots[ev.i] && slots[ev.i].id === me.token && debug.drawn && performance.now() - debug.drawn.t < 200) {
        x = clamp(debug.drawn.x, 12, W - 12); y = clamp(debug.drawn.y, 12, H - 12);
      }
      knockoutEffect(x, y, c, slots[ev.i] && slots[ev.i].ko);
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
        const mine = M.slots.find((x) => x.id === me.token);
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
      if (isMe(ev.i)) fx.tell(`${POWER_ICONS[ev.k]} ${k ? k.title : ev.k}!`, POWER_COLORS[ev.k]);
      fx.feed.push({ power: ev.k, who: ev.i, at: performance.now() });
      if (fx.feed.length > FEED_LINES) fx.feed.shift();
      break;
    }
    case "punch":
      fx.burst(ev.x, ev.y, POWER_COLORS.punch, 30, 10, 4.5, 0.6);
      fx.ring(ev.x, ev.y, POWER_COLORS.punch, 0.4);
      fx.kick(12);
      sound.play("hit", 1);
      break;
    case "overtime": fx.say("Overtime!", T.accent); fx.tell("Next knockout wins", T.text); sound.play("go"); break;
    case "sudden": fx.say("Sudden death!", T.danger); fx.kick(6); sound.play("go"); break;
    case "hit":
      fx.burst(ev.x, ev.y, T.text, Math.round(4 + ev.s), ev.s * 0.5, 3, 0.35);
      fx.kick(Math.min(8, ev.s * 0.4));
      sound.play("hit", Math.min(1, ev.s / 18));
      break;
    case "over": sound.play("win"); break;
  }
}
