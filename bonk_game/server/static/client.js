// bonk web client: lobby, input and drawing. The server runs the game;
// this sends our buttons and draws the state it sends back 30 times a
// second, blending between the last two states for smooth 60 fps motion.
"use strict";

// ---------------------------------------------------------------------------
// Colours (same as bonk_game/ui/theme.py)
// ---------------------------------------------------------------------------
const T = {
  bgTop: "#182134", bgBottom: "#2e4060",
  text: "#f1f5f9", dim: "#a0aec6", faint: "#6e7c96", accent: "#ffd166",
  panel: "rgba(19,27,43,0.78)", danger: "#ef5350",
  rope: "#b08e68", rail: "#7888aa", hazard: "#ef5350",
};
const W = 680, H = 480;
const TICK_MS = 1000 / 30;
const INTERP_DELAY = 50;   // ms behind the newest state we draw at
const MAX_JUMP = 60;       // a bigger move in one tick is a teleport, not blended

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};
function randomToken() {
  const a = new Uint8Array(12);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}
function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function toHex([r, g, b]) {
  return "#" + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
}
const darken = (hex, a) => toHex(rgb(hex).map((c) => c * (1 - a)));
const lighten = (hex, a) => toHex(rgb(hex).map((c) => c + (255 - c) * a));
const mix = (h1, h2, t) => { const a = rgb(h1), b = rgb(h2); return toHex(a.map((c, i) => c + (b[i] - c) * t)); };
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const easeOutBack = (t) => { t = clamp(t, 0, 1); const c = 1.70158; return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2; };

let toastTimer = null;
function toast(text, error = false) {
  const el = $("toast");
  el.textContent = text;
  el.classList.toggle("error", error);
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
}
function status(text) {
  $("status").textContent = text || "";
  $("status").classList.toggle("hidden", !text);
}
function show(screen) {
  for (const id of ["home", "lobby", "game"]) $(id).classList.toggle("hidden", id !== screen);
}

// ---------------------------------------------------------------------------
// App state
// ---------------------------------------------------------------------------
const me = {
  token: store.get("bonk.token") || randomToken(),
  name: store.get("bonk.name", ""),
};
store.set("bonk.token", me.token);

const app = {
  ws: null,
  room: null,
  welcome: null,
  lobby: null,
  match: null,       // the "match" message: slots, map, first_to
  states: [],        // recent [receivedAt, state]
  results: null,
  retry: 0,
  fatal: false,
};

function send(msg) {
  if (app.ws && app.ws.readyState === WebSocket.OPEN) app.ws.send(JSON.stringify(msg));
}
const isHost = () => app.lobby && app.lobby.host === me.token;

// ---------------------------------------------------------------------------
// Home screen
// ---------------------------------------------------------------------------
$("name").value = me.name;
$("name").addEventListener("change", () => {
  me.name = $("name").value.trim().slice(0, 16);
  store.set("bonk.name", me.name);
  send({ type: "name", name: me.name });
});
$("create").addEventListener("click", async () => {
  $("name").dispatchEvent(new Event("change"));
  $("create").disabled = true;
  try {
    const r = await fetch("/api/rooms", { method: "POST" });
    const body = await r.json();
    if (!r.ok) toast(body.error || "Couldn't create a room.", true);
    else openRoom(body.room, true);
  } catch (e) {
    toast("Couldn't create a room. Is the server running?", true);
  } finally {
    $("create").disabled = false;
  }
});
$("join-form").addEventListener("submit", (e) => {
  e.preventDefault();
  $("name").dispatchEvent(new Event("change"));
  const code = $("code").value.trim().toUpperCase();
  if (code.length === 4) openRoom(code, true);
  else toast("Room codes are 4 letters.", true);
});

function openRoom(code, push) {
  app.room = code.toUpperCase();
  app.fatal = false;
  if (push) history.pushState({}, "", `/r/${app.room}`);
  connect();
}

window.addEventListener("popstate", () => route());
function route() {
  const m = location.pathname.match(/^\/r\/([A-Za-z]{4})\/?$/);
  if (m) {
    if (!me.name) {
      // Ask for a name first; joining comes from the form
      show("home");
      $("code").value = m[1].toUpperCase();
      $("name").focus();
      return;
    }
    openRoom(m[1], false);
  } else {
    if (app.ws) { app.fatal = true; app.ws.close(); }
    show("home");
  }
}

// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------
function connect() {
  if (app.ws) { app.ws.onclose = null; app.ws.close(); }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/${app.room}`);
  app.ws = ws;
  status(app.retry ? "Reconnecting…" : "Connecting…");
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "hello", name: me.name, token: me.token }));
  };
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => {
    if (app.ws !== ws || app.fatal) return;
    app.retry = Math.min(app.retry + 1, 5);
    status("Connection lost. Reconnecting…");
    setTimeout(connect, 500 * 2 ** app.retry);
  };
}

function onMessage(msg) {
  switch (msg.type) {
    case "welcome":
      app.welcome = msg;
      app.retry = 0;
      status("");
      fillMapOptions();
      break;
    case "lobby":
      app.lobby = msg;
      document.body.classList.toggle("is-host", isHost());
      renderLobby();
      if (msg.phase === "lobby") { app.match = null; app.results = null; show("lobby"); $("results").classList.add("hidden"); }
      break;
    case "match":
      app.match = msg;
      app.states = [];
      app.results = null;
      fx.reset();
      $("results").classList.add("hidden");
      show("game");
      resize();
      break;
    case "state":
      app.states.push([performance.now(), msg]);
      if (app.states.length > 8) app.states.shift();
      for (const ev of msg.events || []) onEvent(ev, msg);
      break;
    case "results":
      if (!app.match) { show("lobby"); break; }  // joined after the match ended
      app.results = msg;
      showResults(msg);
      break;
    case "error":
      toast(msg.message, true);
      if (msg.fatal) {
        app.fatal = true;
        history.replaceState({}, "", "/");
        show("home");
      }
      break;
  }
}

// ---------------------------------------------------------------------------
// Lobby
// ---------------------------------------------------------------------------
function fillMapOptions() {
  const sel = $("map");
  sel.innerHTML = "";
  for (const m of app.welcome.maps) {
    const o = document.createElement("option");
    o.value = m.name;
    o.textContent = m.title;
    sel.appendChild(o);
  }
  const ft = $("first-to");
  ft.innerHTML = "";
  for (const n of [1, 2, 3, 5, 7, 10, 15, 25, 50, 100]) {
    const o = document.createElement("option");
    o.value = n;
    o.textContent = n;
    ft.appendChild(o);
  }
}

function botLabel(kind) {
  if (kind.startsWith("bot:")) return kind.slice(4)[0].toUpperCase() + kind.slice(5) + " bot";
  return kind.toUpperCase() + " agent";
}

function renderLobby() {
  const L = app.lobby, Wm = app.welcome;
  if (!Wm) return;
  $("room-code").textContent = L.room;
  const host = isHost();
  const s = L.settings;

  // Maps / first-to
  $("map").value = s.map;
  $("map").disabled = !host;
  const mapInfo = Wm.maps.find((m) => m.name === s.map);
  $("map-desc").textContent = mapInfo ? mapInfo.description : "";
  if (![...$("first-to").options].some((o) => +o.value === s.first_to)) {
    const o = document.createElement("option");
    o.value = s.first_to; o.textContent = s.first_to;
    $("first-to").appendChild(o);
  }
  $("first-to").value = s.first_to;
  $("first-to").disabled = !host;

  // Seats: connected people first (that's the match order), then bots
  const ul = $("seats");
  ul.innerHTML = "";
  const people = L.members.filter((m) => m.connected).slice(0, Wm.max_players);
  const away = L.members.filter((m) => !m.connected);
  const bots = s.bots.slice(0, Math.max(0, Wm.max_players - people.length));
  let i = 0;
  for (const m of people) {
    ul.appendChild(seat(i++, m.name + (m.id === L.host ? "  ★" : ""), m.id === me.token ? "you" : "", m.id === me.token));
  }
  bots.forEach((kind, b) => {
    const li = seat(i++, botLabel(kind), "", false);
    if (host) {
      const sel = document.createElement("select");
      for (const opt of L.bot_options) {
        const o = document.createElement("option");
        o.value = opt; o.textContent = botLabel(opt);
        sel.appendChild(o);
      }
      sel.value = kind;
      sel.addEventListener("change", () => {
        const next = s.bots.slice(); next[b] = sel.value;
        send({ type: "settings", bots: next });
      });
      const rm = document.createElement("button");
      rm.className = "remove"; rm.textContent = "✕"; rm.title = "Remove bot";
      rm.addEventListener("click", () => {
        const next = s.bots.slice(); next.splice(b, 1);
        send({ type: "settings", bots: next });
      });
      li.querySelector(".who").textContent = "";
      li.insertBefore(sel, li.querySelector(".tag"));
      li.appendChild(rm);
    }
    ul.appendChild(li);
  });
  for (const m of away) {
    const li = seat(null, m.name, "reconnecting…", false);
    li.classList.add("away");
    ul.appendChild(li);
  }
  $("seat-count").textContent = `${i} / ${Wm.max_players}`;
  $("add-bot").disabled = i >= Wm.max_players;
  const extra = L.members.filter((m) => m.connected).length - Wm.max_players;
  $("spectators").textContent = extra > 0 ? `${extra} more watching (the match is full).` : "";
  $("start").disabled = i < 2;

  // Joined during a match: watch it
  if (L.phase === "match" && !app.match) status("A match is on. You'll play in the next one.");
}

function seat(i, label, tag, you) {
  const li = document.createElement("li");
  li.className = "seat" + (you ? " you" : "");
  const ball = document.createElement("span");
  ball.className = "ball";
  ball.style.background = i === null ? T.faint : app.welcome.colors[i];
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = label;
  const t = document.createElement("span");
  t.className = "tag";
  t.textContent = tag;
  li.append(ball, who, t);
  return li;
}

$("map").addEventListener("change", () => send({ type: "settings", map: $("map").value }));
$("first-to").addEventListener("change", () => send({ type: "settings", first_to: +$("first-to").value }));
$("add-bot").addEventListener("click", () => send({ type: "settings", bots: [...app.lobby.settings.bots, "bot:medium"] }));
$("start").addEventListener("click", () => send({ type: "start" }));
$("again").addEventListener("click", () => send({ type: "start" }));
$("to-lobby").addEventListener("click", () => send({ type: "lobby" }));
$("copy-link").addEventListener("click", async () => {
  const link = `${location.origin}/r/${app.room}`;
  try {
    await navigator.clipboard.writeText(link);
    toast("Invite link copied");
  } catch (e) {
    toast(link);
  }
});

function showResults(msg) {
  const slots = msg.slots || (app.match && app.match.slots) || [];
  const w = msg.winner;
  const el = $("winner");
  if (w === null || w === undefined) {
    el.textContent = "Draw!";
    el.style.color = T.text;
  } else {
    const s = slots[w];
    el.textContent = s && s.id === me.token ? "You win!" : `${s ? s.name : "?"} wins!`;
    el.style.color = s ? s.color : T.text;
  }
  const ol = $("standings");
  ol.innerHTML = "";
  const order = msg.scores.map((sc, i) => i).sort((a, b) => msg.scores[b] - msg.scores[a]);
  for (const i of order) {
    const s = slots[i] || { name: "?", color: T.faint };
    const li = document.createElement("li");
    const ball = document.createElement("span");
    ball.className = "ball";
    Object.assign(ball.style, { width: "16px", height: "16px", borderRadius: "50%", background: s.color, flex: "none" });
    const name = document.createElement("span");
    name.textContent = s.id === me.token ? `${s.name} (you)` : s.name;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = msg.scores[i];
    li.append(ball, name, score);
    ol.appendChild(li);
  }
  $("results").classList.remove("hidden");
  if (w !== null && w !== undefined) fx.confetti(slots[w] ? slots[w].color : T.accent);
}

// ---------------------------------------------------------------------------
// Input: WASD or arrows, Space/Shift for heavy; touch buttons on phones
// ---------------------------------------------------------------------------
const KEYMAP = {
  KeyW: 0, ArrowUp: 0, KeyA: 1, ArrowLeft: 1, KeyS: 2, ArrowDown: 2, KeyD: 3, ArrowRight: 3,
  Space: 4, ShiftLeft: 4, ShiftRight: 4,
};
const held = { keys: new Set(), touch: [0, 0, 0, 0, 0] };
let lastSent = "";

function buttons() {
  const b = [0, 0, 0, 0, 0];
  for (const code of held.keys) b[KEYMAP[code]] = 1;
  held.touch.forEach((v, i) => { if (v) b[i] = 1; });
  return b;
}
function sendInput(force) {
  const b = buttons();
  const key = b.join("");
  if (force || key !== lastSent) {
    lastSent = key;
    send({ type: "input", b });
  }
}
const playing = () => !$("game").classList.contains("hidden") && !app.results;

window.addEventListener("keydown", (e) => {
  if (e.code === "KeyM" && !e.target.matches("input")) { sound.toggle(); return; }
  if (!(e.code in KEYMAP) || !playing()) return;
  e.preventDefault();
  held.keys.add(e.code);
  sendInput();
});
window.addEventListener("keyup", (e) => {
  if (!(e.code in KEYMAP)) return;
  held.keys.delete(e.code);
  sendInput();
});
window.addEventListener("blur", () => { held.keys.clear(); held.touch.fill(0); sendInput(); });
// Resend now and then in case a message was lost
setInterval(() => { if (playing()) sendInput(true); }, 1000);

if ("ontouchstart" in window || navigator.maxTouchPoints > 0) {
  $("touch").classList.remove("hidden");
  for (const btn of $("touch").querySelectorAll("button")) {
    const i = +btn.dataset.b;
    const down = (e) => { e.preventDefault(); held.touch[i] = 1; btn.classList.add("down"); sendInput(); sound.unlock(); };
    const up = (e) => { e.preventDefault(); held.touch[i] = 0; btn.classList.remove("down"); sendInput(); };
    btn.addEventListener("pointerdown", down);
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointercancel", up);
    btn.addEventListener("pointerleave", up);
  }
}

// ---------------------------------------------------------------------------
// Sound: tiny synthesized blips (M toggles)
// ---------------------------------------------------------------------------
const sound = {
  ctx: null,
  muted: store.get("bonk.muted") === "1",
  unlock() {
    if (!this.ctx) {
      try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return; }
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
  },
  toggle() {
    this.muted = !this.muted;
    store.set("bonk.muted", this.muted ? "1" : "0");
    toast(this.muted ? "Sound off" : "Sound on");
  },
  tone(freq, dur, type = "sine", vol = 0.15, slide = 0) {
    if (this.muted || !this.ctx) return;
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
  parts: [], rings: [], shake: 0, banner: null,
  reset() { this.parts = []; this.rings = []; this.shake = 0; this.banner = null; },
  burst(x, y, color, n = 26, speed = 7, size = 4.5, life = 0.7, gravity = true) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, s = speed * (0.3 + Math.random() * 0.9);
      this.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - (gravity ? 2 : 0), color,
        size: size * (0.5 + Math.random() * 0.7), life, age: 0, gravity });
    }
  },
  ring(x, y, color, life = 0.45) { this.rings.push({ x, y, color, life, age: 0 }); },
  kick(n) { this.shake = Math.max(this.shake, n); },
  say(text, color, big = false) { this.banner = { text, color, big, at: performance.now() }; },
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
      const x = clamp(ev.x, 12, W - 12), y = clamp(ev.y, 12, H - 12);
      fx.burst(x, y, c, 34, 9);
      fx.burst(x, y, T.text, 10, 5, 3);
      fx.kick(10);
      sound.play("death");
      if (app.match && !app.match.reset_round_on_kill) {
        const p = state.players[ev.i];
        fx.ring(p[0], p[1], c);
      }
      break;
    }
    case "score": {
      const c = slots[ev.i] ? slots[ev.i].color : T.text;
      sound.play("point");
      const name = slotName(ev.i);
      if (app.match && app.match.reset_round_on_kill) fx.say(name === "You" ? "You score!" : `${name} scores!`, c);
      else fx.say(`+1 ${name}`, c);
      break;
    }
    case "sudden": fx.say("Sudden death!", T.danger); fx.kick(6); sound.play("go"); break;
    case "hit":
      fx.burst(ev.x, ev.y, T.text, Math.round(4 + ev.s), ev.s * 0.5, 3, 0.35);
      fx.kick(Math.min(8, ev.s * 0.4));
      sound.play("hit", Math.min(1, ev.s / 18));
      break;
    case "over": sound.play("win"); break;
  }
}

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------
const canvas = $("canvas");
const ctx = canvas.getContext("2d");
let view = { scale: 1 };

function resize() {
  const vw = window.innerWidth, vh = window.innerHeight;
  const scale = Math.min(vw / W, vh / H);
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${W * scale}px`;
  canvas.style.height = `${H * scale}px`;
  canvas.width = Math.round(W * scale * dpr);
  canvas.height = Math.round(H * scale * dpr);
  view = { scale: scale * dpr };
}
window.addEventListener("resize", resize);

function roundRect(x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function circle(x, y, r, color) {
  ctx.beginPath();
  ctx.arc(x, y, Math.max(0.5, r), 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
}
function poly(points, color) {
  ctx.beginPath();
  points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}
function line(a, b, color, width) {
  ctx.beginPath();
  ctx.moveTo(a[0], a[1]);
  ctx.lineTo(b[0], b[1]);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.stroke();
}

function drawBackground() {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, T.bgTop);
  g.addColorStop(1, T.bgBottom);
  ctx.fillStyle = g;
  ctx.fillRect(-50, -50, W + 100, H + 100);
  const r = ctx.createRadialGradient(W / 2, H * 0.3, 0, W / 2, H * 0.3, W * 0.5);
  r.addColorStop(0, "rgba(255,255,255,0.11)");
  r.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = r;
  ctx.fillRect(0, 0, W, H);
}

function drawEdges() {
  const t = 18, c = "rgba(239,83,80,0.24)", z = "rgba(239,83,80,0)";
  let g = ctx.createLinearGradient(0, 0, t, 0);
  g.addColorStop(0, c); g.addColorStop(1, z);
  ctx.fillStyle = g; ctx.fillRect(0, 0, t, H);
  g = ctx.createLinearGradient(W, 0, W - t, 0);
  g.addColorStop(0, c); g.addColorStop(1, z);
  ctx.fillStyle = g; ctx.fillRect(W - t, 0, t, H);
  g = ctx.createLinearGradient(0, H, 0, H - t);
  g.addColorStop(0, c); g.addColorStop(1, z);
  ctx.fillStyle = g; ctx.fillRect(0, H - t, W, t);
}

function drawRect(s) {
  const [x1, y1, x2, y2] = s.r;
  const x = Math.min(x1, x2), y = Math.min(y1, y2), w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
  const rad = Math.min(5, h / 2, w / 2), lip = Math.min(3, h / 3);
  ctx.fillStyle = "rgba(0,0,0,0.235)";
  roundRect(x, y + 4, w, h, rad); ctx.fill();
  ctx.fillStyle = darken(s.c, 0.28);
  roundRect(x, y, w, h, rad); ctx.fill();
  ctx.fillStyle = s.c;
  roundRect(x, y, w, h - lip, rad); ctx.fill();

  ctx.save();
  roundRect(x, y, w, h, rad); ctx.clip();
  if (s.k === "hazard") {
    ctx.fillStyle = darken(s.c, 0.18);
    for (let sx = x - h; sx < x + w + h; sx += 24) poly([[sx, y + h], [sx + 12, y + h], [sx + 12 + h, y], [sx + h, y]], ctx.fillStyle);
  } else if (s.k === "pad") {
    const size = Math.max(2, Math.min(h / 2, 5)), cy = y + h / 2;
    ctx.strokeStyle = darken(s.c, 0.25);
    ctx.lineWidth = 2;
    for (let cx = x + size * 2; cx < x + w - size; cx += size * 4) {
      ctx.beginPath();
      ctx.moveTo(cx - size, cy + size / 2); ctx.lineTo(cx, cy - size / 2); ctx.lineTo(cx + size, cy + size / 2);
      ctx.stroke();
    }
  }
  ctx.restore();
  if (w > 2 * rad + 2 && h > 4) line([x + rad, y + 1], [x + w - rad - 1, y + 1], lighten(s.c, 0.4), 1.5);
}

function drawPoly(s) {
  poly(s.p.map(([x, y]) => [x, y + 4]), "rgba(0,0,0,0.235)");
  poly(s.p, darken(s.c, 0.28));
  poly(s.f, s.c);
  if (s.k === "hazard") {
    ctx.beginPath(); s.f.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath();
    ctx.strokeStyle = darken(s.c, 0.18); ctx.lineWidth = 2; ctx.stroke();
  } else if (s.k === "pad") {
    const mid = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t)];
    const l = mid(s.f[0], s.f[3], 0.5), r = mid(s.f[1], s.f[2], 0.5);
    line(mid(l, r, 0.2), mid(l, r, 0.8), darken(s.c, 0.25), 2);
  }
  line(s.f[0], s.f[1], lighten(s.c, 0.4), 1.5);
}

function drawBumper(s) {
  circle(s.x, s.y + 4, s.r, "rgba(0,0,0,0.235)");
  circle(s.x, s.y, s.r, darken(s.c, 0.28));
  circle(s.x, s.y - 1.5, s.r - 1.5, s.c);
  if (s.k === "pad") {
    circle(s.x, s.y - 1.5, s.r * 0.62, darken(s.c, 0.22));
    circle(s.x, s.y - 1.5, s.r * 0.42, s.c);
  } else if (s.k === "hazard") {
    circle(s.x, s.y - 1.5, s.r * 0.5, darken(s.c, 0.2));
  }
  circle(s.x - s.r * 0.35, s.y - s.r * 0.4, Math.max(1, s.r * 0.2), lighten(s.c, 0.5));
}

function drawRail(s) {
  line([s.x1, s.y], [s.x2, s.y], darken(T.rail, 0.3), 5);
  line([s.x1, s.y], [s.x2, s.y], T.rail, 3);
  for (const x of [s.x1, s.x2]) { circle(x, s.y, 5, T.rail); circle(x, s.y, 2, darken(T.rail, 0.4)); }
}

function drawShape(s) {
  switch (s.t) {
    case "edges": return drawEdges();
    case "rect": return drawRect(s);
    case "poly": return drawPoly(s);
    case "ball": return drawBumper(s);
    case "line": return line(s.a, s.b, s.c, s.w);
    case "pivot": circle(s.x, s.y, 6, darken(T.rope, 0.3)); return circle(s.x, s.y, 3, lighten(T.rope, 0.3));
    case "rail": return drawRail(s);
  }
}

function drawWalls(walls, t) {
  if (!walls) return;
  const [left, right] = walls;
  const pulse = 0.5 + 0.5 * Math.sin(t * 8);
  ctx.fillStyle = `rgba(239,83,80,${(70 + 30 * pulse) / 255})`;
  if (left > -40) ctx.fillRect(-40, -40, left + 40, H + 80);
  if (right < W + 40) ctx.fillRect(right, -40, W + 40 - right, H + 80);
  for (const x of [left, right]) line([x, -40], [x, H + 40], lighten(T.danger, 0.25 + 0.25 * pulse), 3);
}

function drawPlayer(x, y, r, heavy, color) {
  circle(x, y + 4, r, "rgba(0,0,0,0.215)");
  const rim = darken(color, 0.5);
  const fill = mix(color, darken(color, 0.3), heavy);
  const rimW = 2.5 + heavy * r * 0.35;
  circle(x, y, r, rim);
  circle(x, y, r - rimW, fill);
  circle(x - r * 0.32, y - r * 0.34, Math.max(1, r * 0.22), lighten(fill, 0.55));
}

function drawYouMarker(x, y, r, color) {
  const tx = x, ty = y - r - 9, s = 5;
  const pts = [[tx, ty + s], [tx - s, ty - s * 0.6], [tx + s, ty - s * 0.6]];
  poly(pts, "#ffffff");
  ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.closePath();
  ctx.strokeStyle = darken(color, 0.5); ctx.lineWidth = 1.2; ctx.stroke();
}

function drawOffscreen(x, y, r, color) {
  if (y + r >= 0) return;
  const tx = clamp(x, 14, W - 14), s = 9;
  poly([[tx, 4], [tx - s, 4 + s * 1.4], [tx + s, 4 + s * 1.4]], color);
}

function text(str, size, color, x, y, opts = {}) {
  ctx.font = `${opts.weight || 800} ${size}px ui-rounded, "Nunito", "Avenir Next", "Segoe UI", system-ui, sans-serif`;
  ctx.textAlign = opts.align || "center";
  ctx.textBaseline = "middle";
  ctx.globalAlpha = opts.alpha ?? 1;
  if (opts.shadow !== false) {
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillText(str, x, y + Math.max(1, size / 14));
  }
  ctx.fillStyle = color;
  ctx.fillText(str, x, y);
  ctx.globalAlpha = 1;
}

function pill(x, y, w, h, alpha = 0.78, border = null) {
  ctx.fillStyle = `rgba(19,27,43,${alpha})`;
  roundRect(x, y, w, h, h / 2); ctx.fill();
  if (border) { ctx.strokeStyle = border; ctx.lineWidth = 2; roundRect(x, y, w, h, h / 2); ctx.stroke(); }
}

// Blend the two states either side of the time we draw at
function blendedState(now) {
  const S = app.states;
  if (!S.length) return null;
  const at = now - INTERP_DELAY;
  let i = S.length - 1;
  while (i > 0 && S[i - 1][0] > at) i--;
  if (i === 0) return S[0][1];
  const [ta, a] = S[i - 1], [tb, b] = S[i];
  if (at >= tb) return b;
  const t = clamp((at - ta) / Math.max(1, tb - ta), 0, 1);
  const roundReset = (b.events || []).some((e) => e.e === "round");
  if (roundReset || a.players.length !== b.players.length) return b;
  const players = b.players.map((p, k) => {
    const q = a.players[k];
    if (!q[3] || !p[3] || Math.abs(p[0] - q[0]) > MAX_JUMP || Math.abs(p[1] - q[1]) > MAX_JUMP) return p;
    return [lerp(q[0], p[0], t), lerp(q[1], p[1], t), lerp(q[2], p[2], t), p[3]];
  });
  const level = b.level.map((s, k) => blendShape(a.level[k], s, t));
  return { ...b, players, level };
}

function blendShape(a, b, t) {
  if (!a || a.t !== b.t) return b;
  const pt = (p, q) => (Math.abs(p[0] - q[0]) > MAX_JUMP || Math.abs(p[1] - q[1]) > MAX_JUMP ? q : [lerp(p[0], q[0], t), lerp(p[1], q[1], t)]);
  switch (b.t) {
    case "rect": {
      const [ax1, ay1] = pt([a.r[0], a.r[1]], [b.r[0], b.r[1]]);
      const dx = ax1 - b.r[0], dy = ay1 - b.r[1];
      return { ...b, r: [b.r[0] + dx, b.r[1] + dy, b.r[2] + dx, b.r[3] + dy] };
    }
    case "poly":
      if (a.p.length !== b.p.length) return b;
      return { ...b, p: b.p.map((q, k) => pt(a.p[k], q)), f: b.f.map((q, k) => pt(a.f[k], q)) };
    case "ball": { const [x, y] = pt([a.x, a.y], [b.x, b.y]); return { ...b, x, y }; }
    case "line": return { ...b, a: pt(a.a, b.a), b: pt(a.b, b.b) };
    case "rail": return { ...b, x1: lerp(a.x1, b.x1, t), x2: lerp(a.x2, b.x2, t) };
    default: return b;
  }
}

function drawHud(st, now) {
  const M = app.match, n = st.players.length;
  // Scoreboard: a chip per player
  const chipW = Math.min(n <= 4 ? 120 : 62, (W - 20) / n - 4);
  const x0 = W / 2 - (n * (chipW + 4) - 4) / 2;
  st.players.forEach((p, i) => {
    const slot = M.slots[i];
    const out = M.reset_round_on_kill && !p[3];
    const x = x0 + i * (chipW + 4);
    pill(x, 8, chipW, 30, out ? 0.45 : 0.78, slot.id === me.token ? T.accent : null);
    circle(x + 15, 23, 8, out ? darken(slot.color, 0.55) : slot.color);
    if (n <= 4) {
      const name = slot.id === me.token ? "You" : slot.name;
      ctx.save();
      ctx.beginPath(); ctx.rect(x + 27, 8, chipW - 58, 30); ctx.clip();
      text(name, 12, out ? T.faint : T.text, x + 28, 23, { align: "left", shadow: false });
      ctx.restore();
    }
    text(String(st.scores[i]), 16, out ? T.faint : T.text, x + chipW - 16, 23, { shadow: false });
  });

  // Timer
  if (st.timer !== null && st.timer !== undefined) {
    let label, color;
    if (st.walls) { label = "SUDDEN DEATH"; color = T.danger; }
    else {
      const left = Math.ceil(st.timer);
      label = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
      color = left <= 10 ? T.accent : T.dim;
    }
    ctx.font = `800 13px system-ui`;
    const w = ctx.measureText(label).width + 28;
    pill(W / 2 - w / 2, H - 36, w, 24);
    text(label, 13, color, W / 2, H - 24, { shadow: false });
  }

  // Countdown
  if (st.phase === "countdown" && st.count) {
    const label = st.count_len === 3 ? String(st.count) : (st.count === 2 ? "Ready" : "Set");
    text(label, 64, T.text, W / 2, 150);
  }

  // Banner
  const b = fx.banner;
  if (b) {
    const age = (now - b.at) / 1000;
    if (age < 1.1) {
      const alpha = clamp((1.1 - age) * 4, 0, 1);
      const scale = 0.5 + 0.5 * easeOutBack(age * 4);
      ctx.save();
      const y = b.big ? 150 : 90;
      ctx.translate(W / 2, y);
      ctx.scale(scale, scale);
      text(b.text, b.big ? 46 : 34, b.color, 0, 0, { alpha });
      ctx.restore();
    }
  }

  if (st.phase === "countdown" && st.count_len === 3 && st.tick < 60) {
    text(`${M.title}  ·  first to ${M.first_to}`, 12, T.dim, W / 2, 56, { weight: 600, shadow: false });
  }
}

let lastFrame = performance.now();
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  fx.update(dt);
  if ($("game").classList.contains("hidden") || !app.match) return;
  const st = blendedState(now);
  ctx.setTransform(view.scale, 0, 0, view.scale, 0, 0);
  if (!st) { drawBackground(); text("Get ready…", 24, T.dim, W / 2, H / 2); return; }

  const sx = fx.shake ? (Math.random() - 0.5) * fx.shake : 0;
  const sy = fx.shake ? (Math.random() - 0.5) * fx.shake : 0;
  ctx.setTransform(view.scale, 0, 0, view.scale, sx * view.scale, sy * view.scale);
  drawBackground();
  for (const s of st.level) drawShape(s);
  drawWalls(st.walls, st.t);

  for (const r of fx.rings) {
    const k = r.age / r.life;
    ctx.beginPath(); ctx.arc(r.x, r.y, 20 + 30 * k, 0, Math.PI * 2);
    ctx.strokeStyle = r.color; ctx.globalAlpha = 1 - k; ctx.lineWidth = 3; ctx.stroke(); ctx.globalAlpha = 1;
  }
  for (const p of fx.parts) {
    ctx.globalAlpha = clamp(1 - p.age / p.life, 0, 1);
    circle(p.x, p.y, p.size * (1 - 0.5 * p.age / p.life), p.color);
  }
  ctx.globalAlpha = 1;

  const R = app.match.radius;
  const showNames = st.players.length > 2;
  st.players.forEach((p, i) => {
    if (!p[3]) return;
    const slot = app.match.slots[i];
    drawPlayer(p[0], p[1], R, p[2], slot.color);
  });
  st.players.forEach((p, i) => {
    if (!p[3]) return;
    const slot = app.match.slots[i];
    if (slot.id === me.token) drawYouMarker(p[0], p[1], R, slot.color);
    else if (showNames && slot.kind === "human") text(slot.name.slice(0, 10), 10, "rgba(241,245,249,0.75)", p[0], p[1] - R - 9, { weight: 700 });
    drawOffscreen(p[0], p[1], R, slot.color);
  });

  ctx.setTransform(view.scale, 0, 0, view.scale, 0, 0);
  drawHud(st, now);
}
requestAnimationFrame(frame);

route();
