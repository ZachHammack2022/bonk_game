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
// Ball colours, in the server's order (bonk_game/ui/theme.py PLAYER_COLORS;
// tests/test_profile.py checks they match)
const PALETTE = [
  ["Red", "#ff6b6b"], ["Blue", "#4dabf7"], ["Yellow", "#ffd43b"], ["Purple", "#b197fc"], ["Orange", "#ff922b"],
  ["Green", "#40c057"], ["Pink", "#faa2c1"], ["Cyan", "#3bc9db"], ["White", "#f1f3f5"], ["Brown", "#9c6644"],
];
const PATTERNS = ["plain", "stripes", "dots", "ring", "split", "star", "zigzag", "eyes"];
const PATTERN_NAMES = { plain: "Plain", stripes: "Stripes", dots: "Dots", ring: "Ring", split: "Split", star: "Star", zigzag: "Zigzag", eyes: "Eyes" };
const W = 680, H = 480;
const TICK_MS = 1000 / 30;
const INTERP_DELAY = 50;   // ms behind the newest state we draw at
const MAX_JUMP = 60;       // a bigger move in one tick is a teleport, not blended

// Testing switches: ?lag=150 adds 150 ms of fake round-trip delay;
// ?predict=0 turns off prediction of your own ball.
const params = new URLSearchParams(location.search);
const FAKE_LAG = Math.max(0, +params.get("lag") || 0);
const PREDICT = params.get("predict") !== "0";

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
// Your profile: name, favourite colour and pattern. Kept in this browser
// (no sign-up); sent to each room you join.
const me = {
  token: store.get("bonk.token") || randomToken(),
  name: store.get("bonk.name", ""),
  color: store.get("bonk.color", "") === "" ? null : +store.get("bonk.color"),
  pattern: PATTERNS.includes(store.get("bonk.pattern")) ? store.get("bonk.pattern") : "plain",
};
function saveProfile() {
  store.set("bonk.color", me.color === null ? "" : String(me.color));
  store.set("bonk.pattern", me.pattern);
  renderHomeBall();
}
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
  const ws = app.ws;
  const go = () => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg)); };
  if (FAKE_LAG) setTimeout(go, FAKE_LAG / 2); else go();
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
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (FAKE_LAG) setTimeout(() => { if (app.ws === ws) onMessage(msg); }, FAKE_LAG / 2);
    else onMessage(msg);
  };
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
      // Bring your profile along
      if (me.pattern !== "plain") send({ type: "pattern", pattern: me.pattern });
      if (me.color !== null) send({ type: "color", color: me.color, auto: true });
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
      // Emotes are for players, not people watching
      $("emotes").classList.toggle("hidden", !msg.slots.some((x) => x.id === me.token));
      show("game");
      resize();
      break;
    case "pong": {
      const sample = performance.now() - msg.t;
      net.rtt = net.rtt === null ? sample : net.rtt * 0.8 + sample * 0.2;
      break;
    }
    case "state":
      app.states.push([performance.now(), msg]);
      if (app.states.length > 8) app.states.shift();
      for (const ev of msg.events || []) onEvent(ev, msg);
      break;
    case "emote":
      fx.emotes.push({ slot: msg.slot, id: msg.id, at: performance.now() });
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
        if (app.ws) app.ws.close();
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
  fillSelect($("mode"), app.welcome.modes.map((m) => [m.id, m.title]));
  fillSelect($("gravity"), app.welcome.gravities.map((g) => [g, g[0].toUpperCase() + g.slice(1)]));
}

function fillSelect(sel, pairs) {
  const key = JSON.stringify(pairs);
  if (sel.dataset.key === key) return;
  sel.dataset.key = key;
  sel.innerHTML = "";
  for (const [value, label] of pairs) {
    const o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    sel.appendChild(o);
  }
}

const roundTimeLabel = (t, map) => (t === null ? (map && map.round_time ? `${map.round_time}s (map)` : "Map's") : t === 0 ? "Off" : `${t}s`);
const modeInfo = (id) => app.welcome.modes.find((m) => m.id === id);

function botLabel(kind) {
  if (kind.startsWith("bot:")) return kind.slice(4)[0].toUpperCase() + kind.slice(5) + " bot";
  return kind.toUpperCase() + " agent";
}

const picker = { open: false };

function renderLobby() {
  const L = app.lobby, Wm = app.welcome;
  if (!Wm) return;
  $("room-code").textContent = L.room;
  const host = isHost();
  const s = L.settings;

  // Mode, map and the other settings
  const mode = modeInfo(s.mode);
  $("mode").value = s.mode;
  $("mode").disabled = !host;
  $("mode-desc").textContent = mode.description;
  for (const o of $("map").options) {
    const m = Wm.maps.find((x) => x.name === o.value);
    o.disabled = mode.respawns && !m.respawn_ok;
    o.textContent = m.title + (o.disabled ? " (not for this mode)" : "");
  }
  $("map").value = s.map;
  $("map").disabled = !host;
  const mapInfo = Wm.maps.find((m) => m.name === s.map);
  $("map-desc").textContent = mapInfo ? mapInfo.description : "";
  $("goal-label").textContent = mode.goal_label;
  const goals = mode.goal_choices.includes(s.first_to) ? mode.goal_choices : [...mode.goal_choices, s.first_to].sort((a, b) => a - b);
  fillSelect($("first-to"), goals.map((n) => [n, String(n)]));
  $("first-to").value = s.first_to;
  $("first-to").disabled = !host;
  $("round-time-box").classList.toggle("hidden", !mode.round_time);
  fillSelect($("round-time"), Wm.round_times.map((t) => [JSON.stringify(t), roundTimeLabel(t, mapInfo)]));
  $("round-time").value = JSON.stringify(s.round_time);
  $("round-time").disabled = !host;
  $("gravity").value = s.gravity;
  $("gravity").disabled = !host;
  const teams = s.mode === "teams";
  const mine = L.seats.find((x) => x.id === me.token);
  $("switch-team").classList.toggle("hidden", !teams || !mine);
  if (teams && mine) $("switch-team").textContent = `Switch to ${Wm.team_names[1 - mine.team]}`;

  // Seats, in match order, as the server says they'd be right now
  const ul = $("seats");
  ul.innerHTML = "";
  const order = teams ? [...L.seats].sort((a, b) => a.team - b.team) : L.seats;
  let lastTeam = null;
  for (const seatInfo of order) {
    if (teams && seatInfo.team !== lastTeam) {
      lastTeam = seatInfo.team;
      const head = document.createElement("li");
      head.className = "team-head";
      head.style.color = Wm.team_colors[lastTeam];
      head.textContent = Wm.team_names[lastTeam];
      ul.appendChild(head);
    }
    if (seatInfo.kind === "human") {
      const you = seatInfo.id === me.token;
      const li = seat(seatInfo.color, seatInfo.name + (seatInfo.id === L.host ? "  ★" : ""), you ? "you" : "", you, seatInfo.pattern);
      if (you) {
        const ball = li.querySelector(".ball");
        ball.classList.add("pick");
        ball.title = "Pick your colour";
        ball.setAttribute("role", "button");
        ball.tabIndex = 0;
        const toggle = () => { picker.open = !picker.open; renderLobby(); };
        ball.addEventListener("click", toggle);
        ball.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      } else if (host) {
        li.appendChild(removeButton("Remove from room", () => {
          if (confirm(`Remove ${seatInfo.name} from the room?`)) send({ type: "kick", id: seatInfo.id });
        }));
      }
      ul.appendChild(li);
      if (you && picker.open) ul.appendChild(colorPicker(seatInfo.color));
    } else {
      const b = seatInfo.bot;
      const li = seat(seatInfo.color, botLabel(seatInfo.kind), "", false);
      if (host) {
        const sel = document.createElement("select");
        sel.setAttribute("aria-label", "Bot type");
        for (const opt of L.bot_options) {
          const o = document.createElement("option");
          o.value = opt; o.textContent = botLabel(opt);
          sel.appendChild(o);
        }
        sel.value = seatInfo.kind;
        sel.addEventListener("change", () => {
          const next = s.bots.slice(); next[b] = sel.value;
          send({ type: "settings", bots: next });
        });
        li.querySelector(".who").textContent = "";
        li.insertBefore(sel, li.querySelector(".tag"));
        li.appendChild(removeButton("Remove bot", () => {
          const next = s.bots.slice(); next.splice(b, 1);
          send({ type: "settings", bots: next });
        }));
      }
      ul.appendChild(li);
    }
  }
  for (const m of L.members.filter((m) => !m.connected)) {
    const li = seat(null, m.name, "reconnecting…", false);
    li.classList.add("away");
    ul.appendChild(li);
  }
  const n = L.seats.length;
  $("seat-count").textContent = `${n} / ${Wm.max_players}`;
  $("add-bot").disabled = n >= Wm.max_players;
  const extra = L.members.filter((m) => m.connected).length - Wm.max_players;
  $("spectators").textContent = extra > 0 ? `${extra} more watching (the match is full).` : "";
  $("start").disabled = n < 2;

  // Rematch votes on the results screen
  if (L.phase === "results") {
    const here = L.members.filter((m) => m.connected).length;
    const voted = L.votes.includes(me.token);
    $("vote").textContent = voted ? `Waiting for others… ${L.votes.length}/${here}` : `Play again  ${L.votes.length}/${here}`;
    $("vote").classList.toggle("primary", !voted);
  }

  // Joined during a match: watch it
  if (L.phase === "match" && !app.match) status("A match is on. You'll play in the next one.");
}

function removeButton(title, onClick) {
  const rm = document.createElement("button");
  rm.className = "remove"; rm.textContent = "✕"; rm.title = title;
  rm.setAttribute("aria-label", title);
  rm.addEventListener("click", onClick);
  return rm;
}

function colorPicker(current) {
  const li = document.createElement("li");
  li.className = "picker";
  const taken = new Set(app.lobby.seats.filter((x) => x.kind === "human" && x.id !== me.token).map((x) => x.color));
  // In teams, each side has its own colours
  const mine = app.lobby.seats.find((x) => x.id === me.token);
  const allowed = mine && mine.team !== null && mine.team !== undefined ? new Set(app.welcome.team_palettes[mine.team]) : null;
  app.welcome.colors.forEach((c, i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === current ? " on" : "");
    b.style.background = c;
    b.title = app.welcome.color_names[i];
    b.setAttribute("aria-label", app.welcome.color_names[i]);
    b.disabled = taken.has(i) || (allowed !== null && !allowed.has(i));
    b.addEventListener("click", () => {
      me.color = i; saveProfile();
      send({ type: "color", color: i });
    });
    li.appendChild(b);
  });
  li.appendChild(patternRow(mine ? mine.pattern : me.pattern, mine ? app.welcome.colors[mine.color] : T.faint, (p) => {
    me.pattern = p; saveProfile();
    send({ type: "pattern", pattern: p });
  }));
  return li;
}

// A row of buttons, one per pattern, drawn on a ball of `color`
function patternRow(current, color, onPick) {
  const row = document.createElement("div");
  row.className = "patterns";
  for (const p of PATTERNS) {
    const b = document.createElement("button");
    b.className = "pattern" + (p === current ? " on" : "");
    b.title = PATTERN_NAMES[p];
    b.setAttribute("aria-label", PATTERN_NAMES[p]);
    b.dataset.pattern = p;
    b.appendChild(ballCanvas(30, color, p));
    b.addEventListener("click", () => onPick(p));
    row.appendChild(b);
  }
  return row;
}

// A little canvas with a ball on it (lobby seats, pickers)
function ballCanvas(size, color, pattern) {
  const c = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  c.width = c.height = Math.round(size * dpr);
  c.style.width = c.style.height = size + "px";
  c.className = "ball-canvas";
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  drawBall(g, size / 2, size / 2, size / 2, 0, color, pattern, false);
  return c;
}

// Home screen: your ball, and the editor for it
function renderHomeBall() {
  const color = me.color === null ? PALETTE[0][1] : PALETTE[me.color][1];
  const el = $("home-ball");
  el.innerHTML = "";
  el.appendChild(ballCanvas(40, color, me.pattern));
  $("home-ball-label").textContent = `${me.color === null ? "Any colour" : PALETTE[me.color][0]}, ${PATTERN_NAMES[me.pattern].toLowerCase()}`;
}
function renderProfileEditor() {
  const box = $("profile-colors");
  box.innerHTML = "";
  const any = document.createElement("button");
  any.className = "swatch any" + (me.color === null ? " on" : "");
  any.title = "Any colour"; any.textContent = "?";
  any.setAttribute("aria-label", "Any colour");
  any.addEventListener("click", () => { me.color = null; saveProfile(); renderProfileEditor(); });
  box.appendChild(any);
  PALETTE.forEach(([name, hex], i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === me.color ? " on" : "");
    b.style.background = hex;
    b.title = name;
    b.setAttribute("aria-label", name);
    b.addEventListener("click", () => { me.color = i; saveProfile(); renderProfileEditor(); });
    box.appendChild(b);
  });
  const pat = $("profile-patterns");
  pat.innerHTML = "";
  pat.appendChild(patternRow(me.pattern, me.color === null ? PALETTE[0][1] : PALETTE[me.color][1], (p) => {
    me.pattern = p; saveProfile(); renderProfileEditor();
  }));
  $("profile-preview").innerHTML = "";
  $("profile-preview").appendChild(ballCanvas(72, me.color === null ? PALETTE[0][1] : PALETTE[me.color][1], me.pattern));
}
$("edit-ball").addEventListener("click", () => { renderProfileEditor(); $("profile").classList.remove("hidden"); });
$("profile-close").addEventListener("click", () => $("profile").classList.add("hidden"));
$("profile").addEventListener("click", (e) => { if (e.target === $("profile")) $("profile").classList.add("hidden"); });

function seat(color, label, tag, you, pattern = "plain") {
  const li = document.createElement("li");
  li.className = "seat" + (you ? " you" : "");
  const ball = ballCanvas(22, color === null ? T.faint : app.welcome.colors[color], pattern);
  ball.classList.add("ball");
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
$("mode").addEventListener("change", () => send({ type: "settings", mode: $("mode").value }));
$("round-time").addEventListener("change", () => send({ type: "settings", round_time: JSON.parse($("round-time").value) }));
$("gravity").addEventListener("change", () => send({ type: "settings", gravity: $("gravity").value }));
$("switch-team").addEventListener("click", () => {
  const mine = app.lobby.seats.find((x) => x.id === me.token);
  if (mine) send({ type: "team", team: 1 - mine.team });
});
$("add-bot").addEventListener("click", () => send({ type: "settings", bots: [...app.lobby.settings.bots, "bot:medium"] }));
$("start").addEventListener("click", () => send({ type: "start" }));
$("again").addEventListener("click", () => send({ type: "start" }));
$("vote").addEventListener("click", () => send({ type: "vote" }));
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
  const M = app.match || {};
  const teamWin = msg.winner_team;
  if (msg.team_scores) {
    const mine = slots.find((x) => x.id === me.token);
    if (teamWin === null || teamWin === undefined) { el.textContent = "Draw!"; el.style.color = T.text; }
    else {
      el.textContent = mine && mine.team === teamWin ? "Your team wins!" : `${M.team_names[teamWin]} wins!`;
      el.style.color = M.team_colors[teamWin];
    }
  } else if (w === null || w === undefined) {
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
  const unit = { lives: (v) => `♥${v}`, crown: (v) => `${v} s` }[msg.mode] || String;
  if (msg.team_scores) {
    for (const t of [0, 1].sort((a, b) => msg.team_scores[b] - msg.team_scores[a])) {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = M.team_names[t] + ": " + slots.filter((s) => s.team === t).map((s) => s.id === me.token ? "You" : s.name).join(", ");
      name.style.color = M.team_colors[t];
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = msg.team_scores[t];
      li.append(name, score);
      ol.appendChild(li);
    }
  }
  for (const i of msg.team_scores ? [] : order) {
    const s = slots[i] || { name: "?", color: T.faint };
    const li = document.createElement("li");
    const ball = document.createElement("span");
    ball.className = "ball";
    Object.assign(ball.style, { width: "16px", height: "16px", borderRadius: "50%", background: s.color, flex: "none" });
    const name = document.createElement("span");
    name.textContent = s.id === me.token ? `${s.name} (you)` : s.name;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = unit(msg.scores[i]);
    li.append(ball, name, score);
    ol.appendChild(li);
  }
  renderAwards(msg, slots);
  $("results").classList.remove("hidden");
  $("emotes").classList.add("hidden");
  if (w !== null && w !== undefined) fx.confetti(slots[w] ? slots[w].color : T.accent);
  else if (teamWin !== null && teamWin !== undefined && M.team_colors) fx.confetti(M.team_colors[teamWin]);
}

const AWARD_ICONS = { kos: "💥", hit: "🔨", falls: "🧈", survivor: "🛡️" };

function awardDetail(a) {
  switch (a.id) {
    case "kos": return `${a.value} knockout${a.value === 1 ? "" : "s"}`;
    case "hit": return `power ${Math.round(a.value)}`;
    case "falls": return `fell ${a.value} time${a.value === 1 ? "" : "s"}`;
    case "survivor": return a.value ? `out ${a.value === 1 ? "once" : a.value + " times"}` : "never out";
  }
  return "";
}

function renderAwards(msg, slots) {
  const ul = $("awards");
  ul.innerHTML = "";
  for (const a of msg.awards || []) {
    const li = document.createElement("li");
    li.dataset.award = a.id;
    const icon = document.createElement("span");
    icon.className = "icon";
    icon.textContent = AWARD_ICONS[a.id] || "🏅";
    const body = document.createElement("span");
    body.className = "body";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = a.title;
    const who = document.createElement("span");
    who.className = "who";
    for (const [k, i] of a.slots.entries()) {
      const s = slots[i] || { name: "?", color: T.faint };
      if (k) who.append(" & ");
      const name = document.createElement("b");
      name.style.color = s.color;
      name.textContent = s.id === me.token ? "You" : s.name;
      who.append(name);
    }
    who.append(" · " + awardDetail(a));
    body.append(title, who);
    li.append(icon, body);
    ul.appendChild(li);
  }
  ul.classList.toggle("hidden", !ul.children.length);
}

// ---------------------------------------------------------------------------
// Settings (the ⚙ menu): sound, screen shake, ping and controls. Kept in
// this browser only.
// ---------------------------------------------------------------------------
const ACTIONS = ["up", "left", "down", "right", "heavy"];
const ACTION_LABELS = { up: "Jump / up", left: "Left", down: "Down", right: "Right", heavy: "Go heavy" };
const DEFAULT_KEYS = { up: "KeyW", left: "KeyA", down: "KeyS", right: "KeyD", heavy: "Space" };
// Always work, whatever you rebind
const FIXED_KEYS = { ArrowUp: 0, ArrowLeft: 1, ArrowDown: 2, ArrowRight: 3, ShiftLeft: 4, ShiftRight: 4 };
// Taken by something else (emotes, mute, the menu)
const RESERVED_KEYS = new Set(["Digit1", "Digit2", "Digit3", "Digit4", "KeyM", "Escape", "Tab", "Enter"]);

const prefs = (() => {
  const d = { volume: 0.8, shake: true, ping: true, keys: { ...DEFAULT_KEYS } };
  try {
    const saved = JSON.parse(store.get("bonk.prefs", "{}"));
    return { ...d, ...saved, keys: { ...d.keys, ...(saved.keys || {}) } };
  } catch (e) { return d; }
})();
const savePrefs = () => store.set("bonk.prefs", JSON.stringify(prefs));

let KEYMAP = {};
function buildKeymap() {
  KEYMAP = { ...FIXED_KEYS };
  ACTIONS.forEach((a, i) => { KEYMAP[prefs.keys[a]] = i; });
}
buildKeymap();

function keyName(code) {
  if (!code) return "—";
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  if (code.startsWith("Arrow")) return { ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→" }[code];
  return code.replace(/(Left|Right)$/, " $1").replace("Numpad", "Num ");
}

const menu = { capture: null };  // the action waiting for a key press

function openSettings() {
  renderSettings();
  $("settings").classList.remove("hidden");
  held.keys.clear(); sendInput();
}
function closeSettings() {
  menu.capture = null;
  $("settings").classList.add("hidden");
}
const settingsOpen = () => !$("settings").classList.contains("hidden");

function renderSettings() {
  $("set-volume").value = Math.round(prefs.volume * 100);
  $("set-volume-out").textContent = sound.muted ? "muted" : `${Math.round(prefs.volume * 100)}%`;
  $("set-mute").checked = sound.muted;
  $("set-shake").checked = prefs.shake;
  $("set-ping").checked = prefs.ping;
  const ul = $("set-keys");
  ul.innerHTML = "";
  for (const a of ACTIONS) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = ACTION_LABELS[a];
    const b = document.createElement("button");
    b.className = "key" + (menu.capture === a ? " waiting" : "");
    b.dataset.action = a;
    b.textContent = menu.capture === a ? "Press a key…" : keyName(prefs.keys[a]);
    b.addEventListener("click", () => { menu.capture = menu.capture === a ? null : a; renderSettings(); });
    const also = document.createElement("span");
    also.className = "dim small";
    also.textContent = { up: "or ↑", left: "or ←", down: "or ↓", right: "or →", heavy: "or Shift" }[a];
    li.append(label, b, also);
    ul.appendChild(li);
  }
}

// A key press while waiting to rebind. Returns true if it was used.
function captureKey(e) {
  if (!menu.capture) return false;
  e.preventDefault();
  if (e.code === "Escape") { menu.capture = null; renderSettings(); return true; }
  if (RESERVED_KEYS.has(e.code) || e.code in FIXED_KEYS) {
    toast(`${keyName(e.code)} is already used for something else.`, true);
    return true;
  }
  // Swap if another action had this key
  const other = ACTIONS.find((a) => prefs.keys[a] === e.code);
  if (other) prefs.keys[other] = prefs.keys[menu.capture];
  prefs.keys[menu.capture] = e.code;
  menu.capture = null;
  savePrefs(); buildKeymap(); renderSettings(); updateHelp();
  return true;
}

function updateHelp() {
  const k = prefs.keys;
  const moves = [k.up, k.left, k.down, k.right].map(keyName).join(" ");
  $("controls-help").textContent = `Move with ${moves} or the arrow keys. ${keyName(k.heavy)} or Shift goes heavy. 1–4 for emotes. Esc for settings.`;
}

for (const id of ["open-settings-home", "open-settings-lobby", "open-settings-game"]) {
  $(id).addEventListener("click", (e) => { e.currentTarget.blur(); openSettings(); });
}
$("settings-close").addEventListener("click", closeSettings);
$("settings").addEventListener("click", (e) => { if (e.target === $("settings")) closeSettings(); });
$("set-volume").addEventListener("input", () => {
  prefs.volume = +$("set-volume").value / 100;
  if (sound.muted && prefs.volume > 0) sound.setMuted(false);
  savePrefs(); renderSettings();
});
$("set-volume").addEventListener("change", () => sound.play("point"));
$("set-mute").addEventListener("change", () => { sound.setMuted($("set-mute").checked); renderSettings(); });
$("set-shake").addEventListener("change", () => { prefs.shake = $("set-shake").checked; savePrefs(); });
$("set-ping").addEventListener("change", () => { prefs.ping = $("set-ping").checked; savePrefs(); });
$("set-reset-keys").addEventListener("click", () => {
  prefs.keys = { ...DEFAULT_KEYS }; menu.capture = null;
  savePrefs(); buildKeymap(); renderSettings(); updateHelp();
});

// ---------------------------------------------------------------------------
// Input: WASD (or your keys) or arrows, Space/Shift for heavy; touch buttons
// on phones
// ---------------------------------------------------------------------------
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
  if (key !== lastSent) {
    net.inputs.push({ t: performance.now(), b });
    const old = performance.now() - 3000;
    while (net.inputs.length > 2 && net.inputs[1].t < old) net.inputs.shift();
  }
  if (force || key !== lastSent) {
    lastSent = key;
    send({ type: "input", b });
  }
}
const playing = () => !$("game").classList.contains("hidden") && !app.results;

const EMOTES = ["👋", "😂", "😮", "😤"];
const sendEmote = (id) => { if (playing()) send({ type: "emote", id }); };
for (const b of document.querySelectorAll("#emotes button")) {
  b.addEventListener("click", () => { sendEmote(+b.dataset.e); b.blur(); });
}

window.addEventListener("keydown", (e) => {
  if (settingsOpen()) {
    if (captureKey(e)) return;
    if (e.code === "Escape") closeSettings();
    return;
  }
  if (e.code === "Escape" && !e.target.matches("input")) { openSettings(); return; }
  if (e.code === "KeyM" && !e.target.matches("input")) { sound.toggle(); return; }
  const digit = /^Digit([1-4])$/.exec(e.code);
  if (digit && playing()) { sendEmote(+digit[1] - 1); return; }
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
  document.body.classList.add("touch");
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
  setMuted(m) {
    this.muted = m;
    store.set("bonk.muted", m ? "1" : "0");
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
  parts: [], rings: [], shake: 0, banner: null, note: null, emotes: [], feed: [],
  reset() { this.parts = []; this.rings = []; this.shake = 0; this.banner = null; this.note = null; this.emotes = []; this.feed = []; },
  burst(x, y, color, n = 26, speed = 7, size = 4.5, life = 0.7, gravity = true) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, s = speed * (0.3 + Math.random() * 0.9);
      this.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - (gravity ? 2 : 0), color,
        size: size * (0.5 + Math.random() * 0.7), life, age: 0, gravity });
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
    if (f.crown !== undefined) {
      parts.push([slotName(f.crown), T.text, slots[f.crown].color], ["👑", T.text, null]);
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
      fx.burst(x, y, c, 34, 9);
      fx.burst(x, y, T.text, 10, 5, 3);
      fx.kick(10);
      sound.play("death");
      fx.feed.push({ victim: ev.i, by: ev.by ?? null, wall: !!ev.wall, at: performance.now() });
      if (fx.feed.length > FEED_LINES) fx.feed.shift();
      if (app.match && !app.match.reset_round_on_kill) {
        const p = state.players[ev.i];
        fx.ring(p[0], p[1], c);
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
      fx.feed.push({ crown: ev.i, at: performance.now() });
      if (fx.feed.length > FEED_LINES) fx.feed.shift();
      sound.play("point");
      break;
    }
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

// ---------------------------------------------------------------------------
// Network timing and predicting your own ball (see predict.js)
// ---------------------------------------------------------------------------
const net = {
  rtt: null,                                  // smoothed round trip, ms
  inputs: [{ t: 0, b: [0, 0, 0, 0, 0] }],     // when your buttons changed
};
setInterval(() => { if (app.ws && app.ws.readyState === WebSocket.OPEN) send({ type: "ping", t: performance.now() }); }, 2000);

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
  return BonkPredict.predict(S.players[i], M.physics, S.level, inputs, n, M.radius);
}

// Where to draw your ball: predicted, with corrections from the server
// faded in over ~0.1 s instead of snapping. Null when not predicting.
function ownPosition(now, dt) {
  const M = app.match;
  if (!PREDICT || !M || !app.states.length || typeof BonkPredict === "undefined") return null;
  const i = M.slots.findIndex((s) => s.id === me.token);
  const entry = app.states[app.states.length - 1];
  const S = entry[1];
  if (i < 0 || S.phase !== "play" || !S.players[i][3] || (S.stand_ins || []).includes(i)) {
    own.tick = null; own.offX = own.offY = 0;
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
      }
    }
    own.tick = S.tick;
    own.base = entry;
  }
  const keep = Math.exp(-dt / 0.1);
  own.offX *= keep; own.offY *= keep;
  return [x + own.offX, y + own.offY];
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

function drawPlayer(x, y, r, heavy, color, pattern) {
  drawBall(ctx, x, y, r, heavy, color, pattern, true);
}

// A ball on any canvas context `g`: rim, fill, pattern, shine
function drawBall(g, x, y, r, heavy, color, pattern = "plain", shadow = true) {
  const dot = (cx, cy, rr, c) => { g.beginPath(); g.arc(cx, cy, Math.max(0.5, rr), 0, Math.PI * 2); g.fillStyle = c; g.fill(); };
  if (shadow) dot(x, y + 4, r, "rgba(0,0,0,0.215)");
  else r -= 1;
  const rim = darken(color, 0.5);
  const fill = mix(color, darken(color, 0.3), heavy);
  const rimW = Math.max(1.5, r * 0.18) + heavy * r * 0.35;
  dot(x, y, r, rim);
  const ri = r - rimW;
  dot(x, y, ri, fill);
  if (pattern && pattern !== "plain") {
    g.save();
    g.beginPath(); g.arc(x, y, ri, 0, Math.PI * 2); g.clip();
    drawPattern(g, x, y, ri, pattern, fill);
    g.restore();
  }
  if (pattern !== "eyes") dot(x - r * 0.32, y - r * 0.34, Math.max(1, r * 0.22), lighten(fill, 0.55));
}

function drawPattern(g, x, y, r, pattern, fill) {
  const ink = darken(fill, 0.28);
  const dot = (cx, cy, rr, c) => { g.beginPath(); g.arc(cx, cy, Math.max(0.5, rr), 0, Math.PI * 2); g.fillStyle = c; g.fill(); };
  g.fillStyle = ink; g.strokeStyle = ink;
  switch (pattern) {
    case "stripes":
      g.lineWidth = r * 0.32;
      for (let k = -3; k <= 3; k++) {
        const o = k * r * 0.75;
        g.beginPath(); g.moveTo(x - r + o, y + r); g.lineTo(x + r + o, y - r); g.stroke();
      }
      break;
    case "dots":
      dot(x, y, r * 0.2, ink);
      for (let k = 0; k < 6; k++) {
        const a = k * Math.PI / 3 + Math.PI / 6;
        dot(x + Math.cos(a) * r * 0.62, y + Math.sin(a) * r * 0.62, r * 0.16, ink);
      }
      break;
    case "ring":
      g.lineWidth = r * 0.22;
      g.beginPath(); g.arc(x, y, r * 0.55, 0, Math.PI * 2); g.stroke();
      break;
    case "split":
      g.beginPath(); g.moveTo(x, y - r); g.lineTo(x + r, y - r); g.lineTo(x + r, y + r); g.lineTo(x, y + r); g.closePath(); g.fill();
      break;
    case "star": {
      g.beginPath();
      for (let k = 0; k < 10; k++) {
        const a = -Math.PI / 2 + k * Math.PI / 5, rr = k % 2 ? r * 0.3 : r * 0.72;
        const px = x + Math.cos(a) * rr, py = y + Math.sin(a) * rr + r * 0.06;
        if (k) g.lineTo(px, py); else g.moveTo(px, py);
      }
      g.closePath(); g.fill();
      break;
    }
    case "zigzag":
      g.lineWidth = r * 0.24; g.lineJoin = "round";
      g.beginPath();
      for (let k = 0; k <= 6; k++) {
        const px = x - r + k * r / 3, py = y + (k % 2 ? -r * 0.22 : r * 0.22);
        if (k) g.lineTo(px, py); else g.moveTo(px, py);
      }
      g.stroke();
      break;
    case "eyes":
      for (const s of [-1, 1]) {
        dot(x + s * r * 0.36, y - r * 0.12, r * 0.27, "#ffffff");
        dot(x + s * r * 0.36 + r * 0.07, y - r * 0.08, r * 0.13, "#1d2433");
      }
      break;
  }
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

// Teams: one chip per team with its members' balls
function drawTeamScores(st) {
  const M = app.match;
  const chipW = 190, gap = 10, x0 = W / 2 - chipW - gap / 2;
  const mine = M.slots.find((x) => x.id === me.token);
  [0, 1].forEach((t) => {
    const x = x0 + t * (chipW + gap);
    pill(x, 8, chipW, 30, 0.78, mine && mine.team === t ? T.accent : M.team_colors[t]);
    text(M.team_names[t], 12, M.team_colors[t], x + 14, 23, { align: "left", shadow: false });
    const members = M.slots.map((s, i) => [s, i]).filter(([s]) => s.team === t);
    members.forEach(([s, i], k) => circle(x + 92 + k * 13, 23, 5, st.players[i][3] ? s.color : darken(s.color, 0.55)));
    text(String(st.team_scores[t]), 16, T.text, x + chipW - 16, 23, { shadow: false });
  });
}

function drawCrown(x, y, r) {
  const w = r * 1.1, h = r * 0.6, base = y - r * 0.72;
  const pts = [[x - w / 2, base], [x - w / 2, base - h], [x - w / 4, base - h * 0.45], [x, base - h * 1.1],
    [x + w / 4, base - h * 0.45], [x + w / 2, base - h], [x + w / 2, base]];
  poly(pts, "#ffd166");
  ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.closePath();
  ctx.strokeStyle = "#a0803a"; ctx.lineWidth = 1.5; ctx.stroke();
  circle(x, base - h * 0.35, 2, "#ef5350");
}

function drawHud(st, now) {
  const M = app.match, n = st.players.length;
  if (st.team_scores) drawTeamScores(st);
  // Scoreboard: a chip per player
  else {
  const chipW = Math.min(n <= 4 ? 120 : 62, (W - 20) / n - 4);
  const x0 = W / 2 - (n * (chipW + 4) - 4) / 2;
  st.players.forEach((p, i) => {
    const slot = M.slots[i];
    const out = !p[3];
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
    const score = M.mode === "lives" ? `♥${st.scores[i]}` : String(st.scores[i]);
    text(score, M.mode === "lives" ? 14 : 16, out ? T.faint : M.mode === "lives" ? "#ff8a8a" : T.text, x + chipW - (M.mode === "lives" ? 19 : 16), 23, { shadow: false });
    if (st.crown === i) drawCrown(x + 15, 23, 8);
  });
  }

  // Timer (Knockouts: the match clock)
  if (st.clock !== undefined) {
    const left = Math.ceil(st.clock);
    const label = st.overtime ? "OVERTIME" : `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    const color = st.overtime ? T.accent : left <= 10 ? T.accent : T.dim;
    ctx.font = `800 13px system-ui`;
    const w = ctx.measureText(label).width + 28;
    pill(W / 2 - w / 2, H - 36, w, 24);
    text(label, 13, color, W / 2, H - 24, { shadow: false });
  } else if (st.timer !== null && st.timer !== undefined) {
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

  const note = fx.note;
  if (note) {
    const age = (now - note.at) / 1000;
    if (age < 1.6) text(note.text, 18, note.color, W / 2, 124, { alpha: clamp((1.6 - age) * 3, 0, 1) });
  }

  drawFeed(now);

  if (net.rtt !== null && prefs.ping) {
    text(`${Math.round(net.rtt)} ms`, 10, T.faint, W - 8, H - 10, { align: "right", weight: 600, shadow: false });
  }

  if (st.phase === "countdown" && st.count_len === 3 && st.tick < 60) {
    text(`${M.mode_title}  ·  ${M.title}  ·  ${M.goal}`, 12, T.dim, W / 2, 56, { weight: 600, shadow: false });
  }
}

let lastFrame = performance.now();
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  fx.update(dt);
  if ($("game").classList.contains("hidden") || !app.match) return;
  let st = blendedState(now);
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
  const mine = app.match.slots.findIndex((s) => s.id === me.token);
  const ownAt = ownPosition(now, dt);
  if (ownAt && mine >= 0) {
    // A copy: st may be a stored server state, which prediction still reads
    const players = st.players.slice();
    players[mine] = [ownAt[0], ownAt[1], st.players[mine][2], 1];
    st = { ...st, players };
  }
  st.players.forEach((p, i) => {
    if (!p[3]) return;
    const slot = app.match.slots[i];
    drawPlayer(p[0], p[1], R, p[2], slot.color, slot.pattern);
  });
  if (mine >= 0) debug.drawn = { x: st.players[mine][0], y: st.players[mine][1], t: now };
  st.players.forEach((p, i) => {
    if (!p[3]) return;
    const slot = app.match.slots[i];
    if (st.crown === i) drawCrown(p[0], p[1], R);
    if (slot.id === me.token) drawYouMarker(p[0], p[1] - (st.crown === i ? 8 : 0), R, slot.color);
    else if (showNames && slot.kind === "human") text(slot.name.slice(0, 10), 10, "rgba(241,245,249,0.75)", p[0], p[1] - R - 9, { weight: 700 });
    drawOffscreen(p[0], p[1], R, slot.color);
  });
  // Emote bubbles over balls
  fx.emotes = fx.emotes.filter((e) => now - e.at < 2000);
  for (const e of fx.emotes) {
    const p = st.players[e.slot];
    if (!p || !p[3]) continue;
    const age = (now - e.at) / 1000;
    const pop = easeOutBack(age * 5);
    const x = clamp(p[0], 20, W - 20), y = Math.max(22, p[1] - R - 30);
    ctx.globalAlpha = clamp((2 - age) * 3, 0, 1);
    ctx.fillStyle = "rgba(241,245,249,0.95)";
    roundRect(x - 17 * pop, y - 15 * pop, 34 * pop, 30 * pop, 12 * pop); ctx.fill();
    ctx.globalAlpha = 1;
    text(EMOTES[e.id] || "?", 18 * pop, T.text, x, y + 1, { shadow: false, alpha: clamp((2 - age) * 3, 0, 1) });
  }

  ctx.setTransform(view.scale, 0, 0, view.scale, 0, 0);
  drawHud(st, now);
}
requestAnimationFrame(frame);

updateHelp();
renderHomeBall();
route();
