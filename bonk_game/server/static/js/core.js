// bonk web client. The server runs the game; the browser sends your
// buttons and draws the state it sends back 30 times a second, blending
// between the last two states for smooth 60 fps motion.
//
// The client is a few plain scripts that share one global scope, loaded in
// order by index.html (no build step):
//   core.js      colours, helpers, app state, your profile, home screen, connection
//   lobby.js     the lobby and the ball pickers
//   results.js   the results screen
//   settings.js  the settings menu
//   input.js     keyboard, touch and emotes
//   effects.js   sound, particles, the knockout feed, game events
//   net.js       network timing and predicting your own ball (predict.js)
//   draw.js      drawing the match
//   main.js      start up
// Code that runs as a file loads may only use what earlier files define.
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
// The client's version (the server puts it in the page). Sent in "hello"; a
// tab left open across a deploy is told to refresh.
const CLIENT_VERSION = (document.querySelector('meta[name="bonk-version"]') || {}).content || "dev";

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
  color: (() => {
    const c = Number(store.get("bonk.color", ""));
    return store.get("bonk.color", "") !== "" && Number.isInteger(c) && c >= 0 && c < PALETTE.length ? c : null;
  })(),
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
  restoring: null,   // the host's settings, to put back after a server restart
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
    // reopen: after a dropped connection the server may have restarted and
    // forgotten the room; ask it to make the room again with the same code
    ws.send(JSON.stringify({ type: "hello", name: me.name, token: me.token, version: CLIENT_VERSION,
                             reopen: app.retry > 0, host: app.restoring !== null }));
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (FAKE_LAG) setTimeout(() => { if (app.ws === ws) onMessage(msg); }, FAKE_LAG / 2);
    else onMessage(msg);
  };
  ws.onclose = () => {
    if (app.ws !== ws || app.fatal) return;
    app.retry = Math.min(app.retry + 1, 5);
    status(app.restoring !== null || $("status").textContent.includes("restarting")
      ? "The server is restarting. Reconnecting…" : "Connection lost. Reconnecting…");
    setTimeout(connect, 500 * 2 ** app.retry);
  };
}

// A new client is out: load it. (Unless we only just did, which would mean
// something is serving an old page; then say so instead of looping.)
function refreshForNewVersion(text) {
  app.fatal = true;
  if (app.ws) app.ws.close();
  let last = 0;
  try { last = +sessionStorage.getItem("bonk.refreshed") || 0; } catch (e) { /* private mode */ }
  if (Date.now() - last < 30000) { status(text); return; }
  try { sessionStorage.setItem("bonk.refreshed", String(Date.now())); } catch (e) { /* private mode */ }
  status("A new version is out. Loading it…");
  setTimeout(() => location.reload(), 600);
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
      if (app.restoring && msg.phase === "lobby") {
        if (isHost()) send({ type: "settings", ...app.restoring });
        app.restoring = null;
      }
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
    case "notice":
      toast(msg.message);
      break;
    case "restart":
      // The server is going down for an update; we'll reconnect to the new one
      if (isHost() && app.lobby) app.restoring = { ...app.lobby.settings };
      status(msg.message);
      break;
    case "error":
      if (msg.refresh) { refreshForNewVersion(msg.message); break; }
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
