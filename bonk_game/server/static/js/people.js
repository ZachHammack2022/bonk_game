// bonk web client: Other people. The game browser (public games, Quick
// match, New game); muting someone on your screen, and reporting them (#36).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// The game browser (/play): every game, public and private, in a table to
// filter, sort and join. A private game (it has a password) shows a lock and
// asks for the password when you join (its invite link has it in, so friends
// never see the question). New game lives here too.
//
// It's built for any number of games: the server sends up to a couple of
// hundred (the busiest first) with the totals, and this filters, sorts and
// shows them a page at a time. The server never sends a game's password.
// ---------------------------------------------------------------------------
const PUBLIC_EVERY = 4000;  // ms between looking at the list again
const GAMES_PAGE = 20;      // rows shown before "Show more"
let publicTimer = null;
const browse = {
  data: null,             // the last /api/public answer
  mode: "", map: "", search: "",
  hideLocked: false,      // Hide private games
  sort: "players", desc: true,
  shown: GAMES_PAGE,
};

// The list stays up to date while the home page or the browser is showing
// (the home page shows how many games are on)
function watchPublic(on) {
  clearInterval(publicTimer);
  publicTimer = on ? setInterval(refreshPublic, PUBLIC_EVERY) : null;
  if (on) refreshPublic();
}

let publicText = null;  // (the last answer, to skip redrawing when nothing changed)
async function refreshPublic() {
  // Not while your profile (or another dialog) is open over the page:
  // redrawing what's under its blurred backdrop makes it flicker
  if (document.querySelector(".overlay:not(.hidden)")) return;
  try {
    const r = await fetch("/api/public");
    if (!r.ok) return;
    const text = await r.text();
    if (text === publicText) return;
    publicText = text;
    browse.data = JSON.parse(text);
    renderHomeCount();
    if (!$("browse").classList.contains("hidden")) renderBrowse();
  } catch (e) { /* offline or restarting: next time */ }
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

function renderHomeCount() {
  const d = browse.data;
  const n = d ? d.rooms.length : 0;
  const help = n
    ? `${plural(n, "game")} on right now${d.online ? `, ${plural(d.online, "player")} online` : ""}.`
    : "Join a game or make your own.";
  if ($("find-help").textContent !== help) $("find-help").textContent = help;
}

function openBrowse(push) {
  if (push) history.pushState({}, "", "/play");
  $("name").dispatchEvent(new Event("change"));
  show("browse");
  if (browse.data) renderBrowse();
}

// Which games pass the filters, in the chosen order
function filteredGames() {
  const q = browse.search.trim().toLowerCase();
  const rows = browse.data.rooms.filter((r) =>
    (!browse.hideLocked || !r.locked) &&
    (!browse.mode || r.mode_id === browse.mode) && (!browse.map || r.map_id === browse.map) &&
    (!q || [r.room, r.name || "", r.host || "", r.map, r.mode, ...(r.names || [])].some((t) => t.toLowerCase().includes(q))));
  const key = {
    name: (r) => [(r.name || "").toLowerCase()],
    locked: (r) => [r.locked ? 1 : 0, r.people],
    players: (r) => [r.open ? 1 : 0, r.people, -r.most],
    mode: (r) => [r.mode, r.map],
    map: (r) => [r.map, r.mode],
    status: (r) => [r.playing ? 1 : 0, r.elapsed || 0],
    ping: (r) => [r.ping == null ? Infinity : r.ping],  // (unknown last, going up)
  }[browse.sort];
  const cmp = (a, b) => {
    const ka = key(a), kb = key(b);
    for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
    return a.room < b.room ? -1 : 1;
  };
  rows.sort((a, b) => (browse.desc ? -cmp(a, b) : cmp(a, b)));
  return rows;
}

// The mode and map filters offer every mode and map (NAMES, from the server:
// stats.js), whether or not anyone's playing it right now
function fillFilter(select, names, all) {
  select.replaceChildren(new Option(all, ""), ...Object.entries(names).map(([v, t]) => new Option(t, v)));
}
fillFilter($("filter-mode"), NAMES.modes, "All modes");
fillFilter($("filter-map"), NAMES.maps, "All maps");

function renderBrowse() {
  const d = browse.data;
  const rooms = d.rooms;
  const locked = rooms.filter((r) => r.locked).length;
  const bits = [plural(rooms.length + (d.more || 0), "game") + (locked ? ` (${locked} private)` : ""),
    plural(d.online, "player") + " online"];
  $("browse-summary").textContent = bits.join(" · ");

  const rows = filteredGames();
  const list = $("games-list");
  list.innerHTML = "";
  for (const r of rows.slice(0, browse.shown)) list.appendChild(gameRow(r));
  const filtering = browse.mode || browse.map || browse.search.trim() || browse.hideLocked;
  $("games-empty").classList.toggle("hidden", rows.length > 0);
  $("games-empty-text").textContent = rooms.length
    ? "No games match these filters."
    : "No games right now. Start one and it shows up here.";
  $("clear-filters").classList.toggle("hidden", !filtering || !rooms.length);
  $("empty-public").classList.toggle("hidden", !!rooms.length && !!filtering);
  const left = rows.length - browse.shown;
  $("games-more").classList.toggle("hidden", left <= 0);
  $("games-more").textContent = `Show ${Math.min(left, GAMES_PAGE)} more (${left} hidden)`;
  for (const b of document.querySelectorAll(".games-head [data-sort]")) {
    b.classList.toggle("sorted", b.dataset.sort === browse.sort);
    b.dataset.dir = b.dataset.sort === browse.sort ? (browse.desc ? "desc" : "asc") : "";
    b.setAttribute("aria-sort", b.dataset.sort === browse.sort ? (browse.desc ? "descending" : "ascending") : "none");
  }
}

function cell(cls, ...kids) {
  const el = document.createElement("span");
  el.className = cls;
  el.setAttribute("role", "cell");
  el.append(...kids);
  return el;
}

function gameRow(r) {
  const row = document.createElement("div");
  row.className = "game-row" + (r.open ? "" : " full") + (r.locked ? " locked" : "");
  row.setAttribute("role", "row");

  const name = document.createElement("b");
  name.textContent = r.name || (r.host ? `${r.host}'s room` : "Room");
  const sub = document.createElement("span");
  sub.className = "dim small";
  const tags = [r.room];
  if (r.host && r.name !== `${r.host}'s room`) tags.push(`host ${r.host}`);
  if (r.quick) tags.push("drop-in");
  if (r.power_ups) tags.push("power-ups");
  if (r.gravity && r.gravity !== "normal") tags.push(`${r.gravity} gravity`);
  if (r.speed && r.speed !== "normal") tags.push(`${r.speed} speed`);
  sub.textContent = tags.join(" · ");
  const game = cell("g-game", name, sub);
  if (r.names && r.names.length) game.title = "Playing: " + r.names.join(", ");

  const mode = document.createElement("span");
  mode.textContent = r.mode;

  // A dot per seat: people filled, bots hollow, free seats faint
  const dots = document.createElement("span");
  dots.className = "seat-dots";
  for (let k = 0; k < r.most; k++) {
    const dot = document.createElement("i");
    dot.className = k < r.people ? "p" : k < r.people + r.bots ? "b" : "";
    dots.appendChild(dot);
  }
  const count = document.createElement("span");
  count.className = "small";
  count.textContent = `${r.people}/${r.most}` + (r.bots ? ` · ${plural(r.bots, "bot")}` : "");

  const pill = document.createElement("span");
  pill.className = "pill " + (r.playing ? "on" : "lobby");
  pill.textContent = r.playing ? `Playing${r.elapsed != null ? " " + clock(r.elapsed) : ""}` : "In lobby";

  const b = document.createElement("button");
  b.className = r.open ? "join" : "";
  b.textContent = r.open ? "Join" : "Watch";
  b.setAttribute("aria-label", `${b.textContent} ${name.textContent}: ${r.mode} on ${r.map}`);
  // A game with a password: ask for it here (no need to ask the server first)
  b.addEventListener("click", (e) => { e.stopPropagation(); joinListed(r); });
  row.addEventListener("click", () => b.click());

  const lock = cell("g-lock");
  if (r.locked) {
    lock.innerHTML = icon("lock");
    lock.title = "Private: needs the password";
    lock.setAttribute("aria-label", "Private");
  }

  // The players' round trip: green when smooth, amber, red when laggy
  const ping = document.createElement("span");
  ping.className = "ping-val " + (r.ping == null ? "" : r.ping < 80 ? "good" : r.ping < 160 ? "ok" : "bad");
  ping.textContent = r.ping == null ? "–" : `${r.ping} ms`;
  const pingCell = cell("g-ping", ping);
  pingCell.title = r.ping == null ? "No ping yet" : `The players' round trip to the server: about ${r.ping} ms`;

  row.append(game, cell("g-players", dots, count), cell("g-mode", mode), lock, cell("g-map", r.map),
    cell("g-status", pill), pingCell, cell("g-join", b));
  return row;
}

for (const b of document.querySelectorAll(".games-head [data-sort]")) {
  b.addEventListener("click", () => {
    if (browse.sort === b.dataset.sort) browse.desc = !browse.desc;
    else { browse.sort = b.dataset.sort; browse.desc = b.dataset.sort === "players" || b.dataset.sort === "status"; }
    renderBrowse();
  });
}
$("hide-locked").addEventListener("change", () => { browse.hideLocked = $("hide-locked").checked; browse.shown = GAMES_PAGE; renderBrowse(); });
$("filter-mode").addEventListener("change", () => { browse.mode = $("filter-mode").value; browse.shown = GAMES_PAGE; renderBrowse(); });
$("filter-map").addEventListener("change", () => { browse.map = $("filter-map").value; browse.shown = GAMES_PAGE; renderBrowse(); });
$("browse-search").addEventListener("input", () => { browse.search = $("browse-search").value; browse.shown = GAMES_PAGE; renderBrowse(); });
$("games-more").addEventListener("click", () => { browse.shown += GAMES_PAGE; renderBrowse(); });
$("clear-filters").addEventListener("click", () => {
  Object.assign(browse, { mode: "", map: "", search: "", shown: GAMES_PAGE, hideLocked: false });
  for (const id of ["browse-search", "filter-mode", "filter-map"]) $(id).value = "";
  $("hide-locked").checked = false;
  renderBrowse();
});
function joinListed(r) {
  if (r.locked) askPassword(r.room, false);  // (core.js)
  else openRoom(r.room, true, null);
}

// Enter in the search: the one game it finds, or (for a game that isn't
// listed yet) the 4-letter code you typed
$("browse-search").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const q = $("browse-search").value.trim();
  const found = browse.data ? filteredGames() : [];
  const exact = found.length === 1 ? found[0] : found.find((r) => r.room === q.toUpperCase());
  if (exact) joinListed(exact);
  else if (/^[A-Za-z]{4}$/.test(q)) openRoom(q.toUpperCase(), true);  // (core.js)
});
$("find").addEventListener("click", () => openBrowse(true));
$("browse-back").addEventListener("click", () => leaveRoom(true));

// New game: straight into a public room named "<your name>'s room" (the
// host can rename it, or make it private, in the lobby)
const defaultRoomName = () => `${(me.name || "Player").trim() || "Player"}'s room`;
async function newGame(button) {
  $("name").dispatchEvent(new Event("change"));
  if (button) button.disabled = true;
  try {
    const r = await fetch("/api/rooms", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: defaultRoomName(), password: false }) });
    const body = await r.json();
    if (!r.ok) toast(body.error || "Couldn't create a game.", true);
    else openRoom(body.room, true, body.password);
  } catch (e) {
    toast("Couldn't create a game. Is the server running?", true);
  } finally {
    if (button) button.disabled = false;
  }
}
$("new-game").addEventListener("click", () => newGame($("new-game")));
$("empty-public").addEventListener("click", () => newGame($("new-game")));

// ---------------------------------------------------------------------------
// Mute and report. People are known by their public id (the server never
// shares anyone's token). Mutes last while this page is open.
// ---------------------------------------------------------------------------
const mutes = new Set();
const MUTED_NAME = "Muted player";
const isMuted = (id) => !!id && mutes.has(id);
const shownName = (id, name) => (isMuted(id) ? MUTED_NAME : name);
let person = null;  // { id, name } in the dialog

// A small button next to someone's name that opens the dialog
function personButton(id, name) {
  const b = document.createElement("button");
  b.className = "person-btn icon-button";
  b.innerHTML = icon("more");
  b.title = `${name}: mute or report`;
  b.setAttribute("aria-label", b.title);
  b.addEventListener("click", () => openPerson(id, name));
  return b;
}

// In settings: everyone else in the room, to mute or report from anywhere
// (in a match too)
function renderPeople() {
  const others = app.lobby && app.ws ? app.lobby.members.filter((m) => m.id !== me.id) : [];
  $("settings-people").classList.toggle("hidden", !others.length);
  const ul = $("people-list");
  ul.innerHTML = "";
  for (const m of others) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "public-info";
    name.textContent = shownName(m.id, m.name) + (m.connected ? "" : " (away)");
    li.append(name, personButton(m.id, m.name));
    ul.appendChild(li);
  }
}

function openPerson(id, name) {
  person = { id, name };
  $("person-name").textContent = name;
  $("person-mute").checked = mutes.has(id);
  $("report-note").value = "";
  $("report-send").disabled = false;
  $("report-send").textContent = "Send report";
  $("person").classList.remove("hidden");
}

const closePerson = () => { $("person").classList.add("hidden"); person = null; };
$("person-close").addEventListener("click", closePerson);
$("person").addEventListener("click", (e) => { if (e.target === $("person")) closePerson(); });
$("person-mute").addEventListener("change", () => {
  if (!person) return;
  if ($("person-mute").checked) mutes.add(person.id); else mutes.delete(person.id);
  applyLooks(app.match);
  if (app.lobby && app.welcome) renderLobby();
  renderPeople();
  chat.render();
  if (app.results && !$("results").classList.contains("hidden")) showResults(app.results, true);
});
$("report-send").addEventListener("click", () => {
  if (!person) return;
  send({ type: "report_player", id: person.id, reason: $("report-reason").value, note: $("report-note").value });
  $("report-send").disabled = true;
  $("report-send").textContent = "Sent";
});
