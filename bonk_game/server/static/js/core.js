// bonk web client. The server runs the game; the browser sends your
// buttons and draws the state it sends back 30 times a second, blending
// between the last two states for smooth 60 fps motion.
//
// The client is a few plain scripts that share one global scope, loaded in
// order by index.html (no build step):
//   report.js    playtest reports: ping, late states, rubber-banding, errors
// (netsim.js, loaded before core.js, pretends the network is worse: ?net=mobile;
// clock.js says what moment of the match to draw; dropdown.js draws the list
// a dropdown opens in the page's own style)
//   core.js      colours, helpers, app state, your profile, home screen, connection
//   lobby.js     the lobby and the ball pickers
//   results.js   the results screen
//   settings.js  the settings menu
//   stats.js     your stats: totals, awards and recent matches
//   input.js     keyboard, touch and emotes
//   effects.js   sound, particles, the knockout feed, game events
//   net.js       network timing and predicting your own ball (physics.js, with planck.js)
//   replay.js    the killcam
//   haptics.js   vibration on phones (and in an app shell)
//   draw.js      drawing the match
//   critter.js   the balls: faces, moods, squash and stretch
//   looks.js     trails, hats, knockout effects, and how balls look on your screen
//   super.js     the attack plane (the super power-up): its cutscene, bombs and blasts
//   people.js    the game browser (public and private games, New game); muting and reporting people
//   chat.js      chat in the lobby and over the match
//   account.js   signing in with Google (optional) and your account
//   main.js      start up
// Code that runs as a file loads may only use what earlier files define.
"use strict";

// ---------------------------------------------------------------------------
// Colours (same as bonk_game/ui/theme.py)
// ---------------------------------------------------------------------------
const T = {
  bgTop: "#bfe3ff", bgBottom: "#ffe6f2",
  text: "#3b2c52", dim: "#6b5d85", faint: "#a99bbd", accent: "#ffc21a",
  panel: "rgba(255,255,255,0.88)", danger: "#ef5350",
  rope: "#b08e68", rail: "#b9a9d6", hazard: "#ff7a7a",
  font: "Fredoka, ui-rounded, \"Nunito\", system-ui, sans-serif",
};
// The canvas draws with Fredoka too: make sure it's loaded
try { document.fonts.load(`600 16px Fredoka`); } catch (e) { /* old browser: the fallback font */ }
// Ball colours, in the server's order (bonk_game/ui/theme.py PLAYER_COLORS;
// tests/test_profile.py checks they match)
const PALETTE = [
  ["Red", "#ff6b6b"], ["Blue", "#4dabf7"], ["Yellow", "#ffd43b"], ["Purple", "#b197fc"], ["Orange", "#ff922b"],
  ["Green", "#40c057"], ["Pink", "#faa2c1"], ["Cyan", "#3bc9db"], ["White", "#f1f3f5"], ["Brown", "#9c6644"],
];
// Patterns, as on the server (bonk_game/server/cosmetics.py; a few are for
// signed-in players: see `looks`)
const PATTERNS = ["plain", "stripes", "dots", "ring", "split", "star", "zigzag", "eyes", "swirl", "smile",
                  "heart", "checker", "galaxy", "flame", "bolt", "target"];
const PATTERN_NAMES = { plain: "Plain", stripes: "Stripes", dots: "Dots", ring: "Ring", split: "Split", star: "Star", zigzag: "Zigzag", eyes: "Eyes",
                        swirl: "Swirl", smile: "Smile", heart: "Heart", checker: "Checker", galaxy: "Galaxy",
                        flame: "Flame", bolt: "Bolt", target: "Target" };
// What a ball can wear besides its colour, and what you've unlocked. The
// server sends the catalogue with /api/me (account.js) and checks each pick.
const looks = {
  KINDS: ["pattern", "trail", "hat", "ko"],
  DEFAULT: { pattern: "plain", trail: "none", hat: "none", ko: "pop" },
  LABELS: { pattern: "Pattern", trail: "Trail", hat: "Hat", ko: "Knockout effect" },
  catalog: null,   // {kind: [{id, name, how, unlocked, member}]}
  item(kind, id) { return this.catalog ? this.catalog[kind].find((x) => x.id === id) : null; },
  // Can you wear it? (Until the catalogue arrives, what you saved; the
  // server checks anyway)
  ok(kind, id) {
    if (!this.catalog) return typeof id === "string" && (kind !== "pattern" || PATTERNS.includes(id));
    const it = this.item(kind, id);
    return !!it && it.unlocked;
  },
  name(kind, id) { const it = this.item(kind, id); return it ? it.name : kind === "pattern" ? PATTERN_NAMES[id] || id : id; },
  // How to unlock it, with how far you've got
  how(it) { return it.how; },
  // A new catalogue (after signing in, or a match): say what's newly unlocked
  set(catalog) {
    const before = this.catalog;
    this.catalog = catalog;
    if (!before) return;
    const fresh = [];
    for (const kind of this.KINDS) {
      for (const it of catalog[kind] || []) {
        const was = before[kind] && before[kind].find((x) => x.id === it.id);
        if (it.unlocked && was && !was.unlocked) fresh.push(`${it.name} ${kind === "ko" ? "knockout" : kind}`);
      }
    }
    if (fresh.length) toast(`Unlocked: ${fresh.join(", ")}. Pick it in Customize.`);
  },
};
const W = 680, H = 480;
const TICK_MS = 1000 / 30;
const playClock = BonkClock.make(TICK_MS);  // what moment of the match to draw (clock.js)
const STATES_KEPT = 16;   // enough to draw up to the longest delay (clock.js) behind the newest
const MAX_JUMP = 60;       // a bigger move in one tick is a teleport, not blended

// Testing switches: ?net=mobile (or ?lag=150&jitter=40...) pretends the
// network is worse than it is (see netsim.js); ?predict=0 turns off
// prediction of your own ball, ?predict_others=0 of the balls near it.
const params = new URLSearchParams(location.search);
const NET_SIM = BonkNetSim.fromParams(params);
const fakeNet = NET_SIM && BonkNetSim.make(NET_SIM);
const PREDICT = params.get("predict") !== "0";
const PREDICT_OTHERS = params.get("predict_others") !== "0";
// The client's version (the server puts it in the page). Sent in "hello"; a
// tab left open across a deploy is told to refresh.
const CLIENT_VERSION = (document.querySelector('meta[name="bonk-version"]') || {}).content || "dev";

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
// One of the icons in index.html's sprite, as markup: icon("gear")
const icon = (name) => `<svg class="i" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  remove(k) { try { localStorage.removeItem(k); } catch (e) { /* private mode */ } },
};
// Opened from the home screen (the web app; install.js)?
function installedApp() {
  try {
    return navigator.standalone === true ||
      matchMedia("(display-mode: standalone), (display-mode: fullscreen)").matches;
  } catch (e) { return false; }
}
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
  for (const id of ["home", "browse", "leaderboard", "lobby", "game"]) $(id).classList.toggle("hidden", id !== screen);
  if (screen !== "game" && typeof music !== "undefined") music.want("lobby");  // (music.js: matches pick their own)
  watchPublic(screen === "home" || screen === "browse");  // (people.js)
  if (typeof friends !== "undefined") friends.watch(screen === "home" || screen === "browse");
}

// ---------------------------------------------------------------------------
// App state
// ---------------------------------------------------------------------------
// Your profile: name, ball, settings, lifetime stats and recent matches
// (static/profile.js has the format). Nothing else reads or writes it.
// - As a guest it's kept in this browser (KEY).
// - Signed in (js/account.js), it's your account's, kept on the server; a
//   copy (ACCOUNT_KEY) lets the page start with it. Changes to your name,
//   ball and settings go to the server; the server records your matches.
const profileStore = {
  KEY: "bonk.profile",
  ACCOUNT_KEY: "bonk.account",
  current: null,
  user: null,            // signed in: { id, name, email }
  get() {
    if (!this.current) this.current = this.load();
    return this.current;
  },
  load() {
    try {
      const a = JSON.parse(store.get(this.ACCOUNT_KEY, "null"));
      const p = a && BonkProfile.validate(a.profile);
      if (p && a.user && a.user.id) { this.user = a.user; return p; }
    } catch (e) { /* unreadable: as a guest */ }
    return this.loadGuest();
  },
  loadGuest() {
    let p = null;
    try { p = BonkProfile.validate(JSON.parse(store.get(this.KEY, "null"))); } catch (e) { /* unreadable: start again */ }
    if (p) return p;
    // First time (or saved before profiles): bring the old separate keys in
    p = BonkProfile.empty(randomToken());
    p.name = store.get("bonk.name", "").slice(0, 16);
    const c = store.get("bonk.color", "");
    if (c !== "" && Number.isInteger(+c) && +c >= 0 && +c < PALETTE.length) p.color = +c;
    if (PATTERNS.includes(store.get("bonk.pattern"))) p.pattern = store.get("bonk.pattern");
    p.muted = store.get("bonk.muted") === "1";
    try { p.prefs = JSON.parse(store.get("bonk.prefs", "{}")) || {}; } catch (e) { /* defaults */ }
    this.save(p);
    for (const k of ["bonk.name", "bonk.color", "bonk.pattern", "bonk.muted", "bonk.prefs"]) store.remove(k);
    return p;
  },
  save(p) {
    this.current = p;
    if (this.user) {
      store.set(this.ACCOUNT_KEY, JSON.stringify({ user: this.user, profile: p }));
      account.push(p);
    } else store.set(this.KEY, JSON.stringify(p));
  },
  update(fn) { this.save(fn(this.get())); },
  // One more match (a history entry: profile.js). Signed in, the server
  // records it too (the same match counts once), and account.js fetches
  // the server's copy afterwards.
  record(entry) {
    this.update((p) => BonkProfile.record(p, entry));
    if (this.user) account.refreshSoon();
  },
};

// You, in rooms: your token (a random id the server knows you by; not part
// of the profile, so a profile file can't be used to take your seat) and
// your profile's name and ball
const me = {
  token: store.get("bonk.token") || randomToken(),
  get name() { return profileStore.get().name; },
  set name(v) { profileStore.update((p) => ({ ...p, name: v })); },
  get color() { const c = profileStore.get().color; return c !== null && c < PALETTE.length ? c : null; },
  set color(v) { profileStore.update((p) => ({ ...p, color: v })); },
  // What your ball wears (looks.KINDS): what you picked, if you can wear it
  look(kind) { const v = profileStore.get()[kind]; return looks.ok(kind, v) ? v : looks.DEFAULT[kind]; },
  setLook(kind, v) { profileStore.update((p) => ({ ...p, [kind]: v })); },
  get pattern() { return this.look("pattern"); },
  set pattern(v) { this.setLook("pattern", v); },
  // A colour of your own ("#rrggbb"): signed in only
  get ownColor() { return profileStore.user ? profileStore.get().own_color || null : null; },
  set ownColor(v) { profileStore.update((p) => ({ ...p, own_color: v })); },
  // Your ball's colour as it looks: your own, your favourite, or the first
  get ballHex() { return this.ownColor || (this.color === null ? PALETTE[0][1] : PALETTE[this.color][1]); },
};
// (me.color = ... and me.pattern = ... save straight away)
function saveProfile() {
  renderHomeBall();
  if (app.ws && app.welcome) sendLooks();  // (in a room: your seat follows)
}
// Your ball's colour and look, to the room (a colour someone else has is
// skipped quietly: you get it when it's free)
function sendLooks() {
  send({ type: "look", ...Object.fromEntries(looks.KINDS.map((k) => [k, me.look(k)])), auto: true });
  if (me.color !== null) send({ type: "color", color: me.color, auto: true });
  send({ type: "own_color", color: me.ownColor || null, auto: true });
}
store.set("bonk.token", me.token);

const app = {
  ws: null,
  room: null,
  password: null,    // the room's password, if it has one (sent in "hello")
  invite: null,       // [code, password] from a link opened before you had a name
  welcome: null,
  lobby: null,
  match: null,       // the "match" message: slots, map, first_to
  states: [],        // recent [receivedAt, state]
  last: null,        // the newest full state (deltas build on it: delta.js)
  results: null,
  retry: 0,
  fatal: false,
  restoring: null,   // the host's settings, to put back after a server restart
  away: false,       // in the lobby while a match is on (lobby.js: goToLobby)
};

function send(msg) {
  const ws = app.ws;
  const go = () => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg)); };
  if (fakeNet) fakeNet.up(go); else go();
}
const isHost = () => app.lobby && app.lobby.host === me.id;

// ---------------------------------------------------------------------------
// Home screen
// ---------------------------------------------------------------------------
$("name").value = me.name;
$("name").addEventListener("change", () => {
  me.name = $("name").value.trim().slice(0, 16);
  send({ type: "name", name: me.name });
});
// Came with an invite link before you had a name: the home page offers that
// game (after you've typed a name), or the list of every game instead
function showInvite(code, password) {
  app.invite = code ? [code, password || null] : null;
  $("join-form").classList.toggle("hidden", !code);
  $("home-play").classList.toggle("hidden", !!code);
  if (code) $("join-code").textContent = `Join game ${code}`;
}
$("join-form").addEventListener("submit", (e) => {
  e.preventDefault();
  if (!app.invite) return;
  $("name").dispatchEvent(new Event("change"));
  const [code, password] = app.invite;
  showInvite(null);
  openRoom(code, true, password || undefined);
});
$("join-other").addEventListener("click", () => { showInvite(null); openBrowse(true); });  // (people.js)

// A room's link: with its password, if it has one, so it's filled in for you
const roomLink = (code, password) => `/r/${code}` + (password ? `?pw=${encodeURIComponent(password)}` : "");

// password: the room's (from its invite link, or typed in); undefined keeps
// the one we have for this room
function openRoom(code, push, password) {
  code = code.toUpperCase();
  if (password !== undefined || code !== app.room) app.password = password || null;
  app.room = code;
  app.fatal = false;
  if (push) history.pushState({}, "", roomLink(app.room, app.password));
  connect();
}

// The game is private and we don't have its password (or it's wrong): ask
function askPassword(code, wrong) {
  $("pw-text").textContent = `Game ${code} is private. Type its password, or ask whoever invited you for their invite link (it has the password in).`;
  $("pw-wrong").classList.toggle("hidden", !wrong);
  $("pw-input").value = wrong ? $("pw-input").value : "";
  $("pw-dialog").dataset.room = code;
  $("pw-dialog").classList.remove("hidden");
  $("pw-input").focus();
  $("pw-input").select();
}
$("pw-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const pw = $("pw-input").value.trim();
  if (!pw) return;
  $("pw-dialog").classList.add("hidden");
  openRoom($("pw-dialog").dataset.room, false, pw);
  history.replaceState({}, "", roomLink(app.room, pw));
});
// Not joining after all: back to wherever we were
function closePassword() {
  $("pw-dialog").classList.add("hidden");
  if (app.ws) return;
  app.room = null; app.password = null;
  const browsing = !$("browse").classList.contains("hidden");
  history.replaceState({}, "", browsing ? "/play" : "/");
  if (!browsing) show("home");
}
$("pw-cancel").addEventListener("click", closePassword);
$("pw-dialog").addEventListener("click", (e) => { if (e.target === $("pw-dialog")) closePassword(); });

window.addEventListener("popstate", () => route());
function route() {
  const m = location.pathname.match(/^\/r\/([A-Za-z]{4})\/?$/);
  if (m) {
    const pw = new URLSearchParams(location.search).get("pw");
    if (!me.name) {
      // Ask for a name first; joining comes from the form
      show("home");
      showInvite(m[1].toUpperCase(), pw);
      $("name").focus();
      return;
    }
    openRoom(m[1], false, pw || undefined);
  } else if (/^\/leaderboard\/?$/.test(location.pathname)) {
    showInvite(null);
    leaveRoom();
    openLeaderboard(false);  // (rating.js)
  } else if (/^\/play\/?$/.test(location.pathname)) {
    showInvite(null);
    leaveRoom();
    openBrowse(false);  // (people.js)
  } else {
    showInvite(null);
    leaveRoom();
  }
}

// Leave the room for good (the ← Leave button, or Back in the browser):
// your seat goes now, rather than being kept for a reconnect
function leaveRoom(push) {
  const ws = app.ws;
  if (ws) {
    playtest.flush();
    app.fatal = true;
    // (Straight onto the socket, not through ?net='s pretend delay: it's
    // about to close)
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "leave" }));
    ws.close();
  }
  replayer.stop();
  chat.reset([]);
  app.ws = null; app.room = null; app.password = null; app.lobby = null; app.match = null; app.results = null; app.away = false;
  app.states = []; app.last = null; app.retry = 0;
  $("results").classList.add("hidden");
  $("killcam").classList.add("hidden");
  status("");
  if (push) history.pushState({}, "", "/");
  show("home");
}
$("leave").addEventListener("click", () => leaveRoom(true));
$("leave-results").addEventListener("click", () => leaveRoom(true));

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
                             reopen: app.retry > 0, host: app.restoring !== null,
                             installed: installedApp(),
                             tz: -new Date().getTimezoneOffset(),  // (your clock: time-of-day badges)
                             ...(app.password ? { password: app.password } : {}) }));
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (fakeNet) fakeNet.down(() => { if (app.ws === ws) onMessage(msg); });
    else onMessage(msg);
  };
  ws.onclose = () => {
    if (app.ws !== ws || app.fatal) return;
    app.retry = Math.min(app.retry + 1, 5);
    playtest.reconnect();
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

// Add a finished match to your history, if you played in it. Returns the
// badges it earned you (badges.js), and how close you are to the next one
function recordMatch(msg) {
  const slots = msg.slots || [];
  const i = slots.findIndex((s) => s.id === me.id);
  if (i < 0 || !msg.summaries || !msg.match_id) return null;
  const before = profileStore.get().stats;
  profileStore.record({ id: msg.match_id, at: msg.at, mode: msg.mode, map: msg.map, ...msg.summaries[i],
                        hour: new Date(msg.at * 1000).getHours(),  // (your clock's: badges)
                        players: slots.length, people: slots.filter((s) => s.kind === "human").length });
  return badgeReport(before, profileStore.get().stats);
}

function onMessage(msg) {
  switch (msg.type) {
    case "welcome":
      app.welcome = msg;
      me.id = msg.you;  // how the others know you (your token stays a secret)
      app.retry = 0;
      status("");
      fillMapOptions();
      playtest.on = !!msg.playtest;
      chat.reset(msg.chat);
      playtest.sendErrors();
      sendLooks();  // (bring your profile along)
      break;
    case "lobby":
      app.lobby = msg;
      // Keep the password (for reconnecting after a restart, and the address
      // bar's link) in step with the host's
      if ((msg.settings.password || null) !== app.password) {
        app.password = msg.settings.password || null;
        history.replaceState({}, "", roomLink(app.room, app.password));
      }
      document.body.classList.toggle("is-host", isHost());
      renderLobby();
      if (app.restoring && msg.phase === "lobby") {
        // (Not the password: the room got that back when it was made again)
        const settings = { ...app.restoring };
        delete settings.password;
        if (isHost()) send({ type: "settings", ...settings });
        app.restoring = null;
      }
      if (msg.phase === "lobby") { app.away = false; replayer.stop(); $("killcam").classList.add("hidden"); playtest.flush(); app.match = null; app.results = null; show("lobby"); $("results").classList.add("hidden"); }
      break;
    case "match":
      app.away = false;
      music.want(music.forMap(msg.map));  // (each map has its own)
      $("go-lobby").classList.remove("hidden");
      app.match = msg;
      applyLooks(msg);
      app.states = [];
      app.last = null;
      app.results = null;
      playClock.reset();
      stalls.reset();
      replayer.stop();
      replayer.recent = [];
      $("killcam").classList.add("hidden");
      playtest.start(!msg.slots.some((x) => x.id === me.id));
      fx.reset();
      $("results").classList.add("hidden");
      // Emotes are for players, not people watching
      $("emotes").classList.toggle("hidden", !msg.slots.some((x) => x.id === me.id));
      show("game");
      resize();
      break;
    case "pong": {
      const sample = performance.now() - msg.t;
      net.rtt = net.rtt === null ? sample : net.rtt * 0.8 + sample * 0.2;
      playtest.ping(sample);
      break;
    }
    case "state":
    case "d": {
      // Mostly deltas: just what changed since the last tick
      const S = msg.type === "state" ? msg : BonkDelta.apply(app.last, msg);
      playtest.state(!!S);
      stalls.state(performance.now());
      if (!S) break;  // missed the state it builds on: wait for the next full one
      app.last = S;
      replayer.keep(S);
      if (replayer.active) break;  // (watching the killcam)
      app.states.push([performance.now(), S]);
      if (app.states.length > STATES_KEPT) app.states.shift();
      playClock.arrive(S.tick, performance.now());
      for (const ev of S.events || []) onEvent(ev, S);
      break;
    }
    case "seat": {
      // Someone who joined during the match took over a bot's seat (maybe you)
      if (!app.match) break;
      app.match.slots[msg.slot] = msg.info;
      applyLooks(app.match);
      if (msg.info.id === me.id) { $("emotes").classList.remove("hidden"); sendInput(true); }
      break;
    }
    case "emote":
      if (app.match && app.match.slots[msg.slot] && isMuted(app.match.slots[msg.slot].id)) break;
      fx.emotes.push({ slot: msg.slot, id: msg.id, at: performance.now() });
      break;
    case "results":
      if (!app.match) { show("lobby"); break; }  // joined after the match ended
      app.results = msg;
      app.earned = recordMatch(msg);  // (the badges it earned you: badges.js)
      showResults(msg);
      playtest.finish();
      showReplayButtons(msg);
      break;
    case "chat":
      chat.add(msg);
      break;
    case "notice":
      toast(msg.message);
      if (msg.friends) friends.refresh();  // (friends.js: a request, or a new friend)
      break;
    case "restart":
      // The server is going down for an update; we'll reconnect to the new one
      if (isHost() && app.lobby) app.restoring = { ...app.lobby.settings };
      status(msg.message);
      break;
    case "error":
      if (msg.refresh) { refreshForNewVersion(msg.message); break; }
      if (msg.password) {
        // The room has a password: ask for it, rather than going home
        app.fatal = true;
        if (app.ws) app.ws.close();
        app.ws = null;
        status("");
        askPassword(app.room, msg.wrong);
        break;
      }
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
