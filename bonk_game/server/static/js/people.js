// bonk web client: Other people. The game browser (public games, Quick
// match, New game); muting someone on your screen, and reporting them (#36).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// The game browser (/play): every public game in a table to filter, sort and
// join; private games by their code. Quick match and New game live here too.
//
// It's built for any number of games: the server sends up to a couple of
// hundred (the busiest first) with the totals, and this filters, sorts and
// shows them a page at a time. Private games are never listed (only how many
// there are), so they stay private.
// ---------------------------------------------------------------------------
const PUBLIC_EVERY = 4000;  // ms between looking at the list again
const GAMES_PAGE = 20;      // rows shown before "Show more"
let publicTimer = null;
const browse = {
  data: null,             // the last /api/public answer
  show: "all",            // all | open | lobby
  mode: "", map: "", search: "",
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

async function refreshPublic() {
  try {
    const r = await fetch("/api/public");
    if (!r.ok) return;
    browse.data = await r.json();
    renderHomeCount();
    if (!$("browse").classList.contains("hidden")) renderBrowse();
  } catch (e) { /* offline or restarting: next time */ }
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

function renderHomeCount() {
  const d = browse.data;
  const n = d ? d.rooms.length : 0;
  $("find-help").textContent = n
    ? `${plural(n, "public game")} on right now${d.online ? `, ${plural(d.online, "player")} online` : ""}.`
    : "See every public game and pick one to join.";
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
    (browse.show !== "open" || r.open) && (browse.show !== "lobby" || !r.playing) &&
    (!browse.mode || r.mode_id === browse.mode) && (!browse.map || r.map_id === browse.map) &&
    (!q || [r.room, r.host || "", r.map, r.mode, ...(r.names || [])].some((t) => t.toLowerCase().includes(q))));
  const key = {
    players: (r) => [r.open ? 1 : 0, r.people, -r.most],
    mode: (r) => [r.mode, r.map],
    map: (r) => [r.map, r.mode],
    status: (r) => [r.playing ? 1 : 0, r.elapsed || 0],
  }[browse.sort];
  const cmp = (a, b) => {
    const ka = key(a), kb = key(b);
    for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
    return a.room < b.room ? -1 : 1;
  };
  rows.sort((a, b) => (browse.desc ? -cmp(a, b) : cmp(a, b)));
  return rows;
}

// The mode and map filters offer what's being played right now (and keep
// the one picked, even if its last game just ended)
function fillFilter(select, pairs, picked, all) {
  const want = [["", all], ...pairs];
  if (picked && !pairs.some(([v]) => v === picked)) want.push([picked, picked]);
  const now = Array.from(select.options, (o) => o.value + "|" + o.textContent).join(",");
  if (now === want.map(([v, t]) => v + "|" + t).join(",")) return;
  select.innerHTML = "";
  for (const [v, t] of want) select.add(new Option(t, v, false, v === picked));
}

function renderBrowse() {
  const d = browse.data;
  const rooms = d.rooms;
  const bits = [plural(rooms.length + (d.more || 0), "public game"), plural(d.online, "player") + " online"];
  if (d.private) bits.push(plural(d.private, "private game") + " (join with a code)");
  $("browse-summary").textContent = bits.join(" · ");
  const uniq = (key, title) => [...new Map(rooms.map((r) => [r[key], r[title]])).entries()].sort((a, b) => (a[1] < b[1] ? -1 : 1));
  fillFilter($("filter-mode"), uniq("mode_id", "mode"), browse.mode, "All modes");
  fillFilter($("filter-map"), uniq("map_id", "map"), browse.map, "All maps");

  const rows = filteredGames();
  const list = $("games-list");
  list.innerHTML = "";
  for (const r of rows.slice(0, browse.shown)) list.appendChild(gameRow(r));
  const filtering = browse.show !== "all" || browse.mode || browse.map || browse.search.trim();
  $("games-empty").classList.toggle("hidden", rows.length > 0);
  $("games-empty-text").textContent = rooms.length
    ? "No games match these filters."
    : "No public games right now. Start one and it shows up here for anyone to join.";
  $("clear-filters").classList.toggle("hidden", !filtering || !rooms.length);
  $("empty-public").classList.toggle("hidden", !!rooms.length && !!filtering);
  $("empty-quick").classList.toggle("hidden", !!rooms.length && !!filtering);
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
  row.className = "game-row" + (r.open ? "" : " full");
  row.setAttribute("role", "row");

  const name = document.createElement("b");
  name.textContent = r.host ? `${r.host}'s game` : "Public game";
  const sub = document.createElement("span");
  sub.className = "dim small";
  const tags = [r.room];
  if (r.quick) tags.push("drop-in");
  if (r.power_ups) tags.push("power-ups");
  if (r.gravity && r.gravity !== "normal") tags.push(`${r.gravity} gravity`);
  if (r.speed && r.speed !== "normal") tags.push(`${r.speed} speed`);
  sub.textContent = tags.join(" · ");
  const game = cell("g-game", name, sub);
  if (r.names && r.names.length) game.title = "Playing: " + r.names.join(", ");

  const mode = document.createElement("span");
  mode.textContent = r.mode;
  const goal = document.createElement("span");
  goal.className = "dim small";
  goal.textContent = r.goal;

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
  b.addEventListener("click", (e) => { e.stopPropagation(); openRoom(r.room, true); });
  row.addEventListener("click", () => b.click());

  row.append(game, cell("g-mode", mode, goal), cell("g-map", r.map), cell("g-players", dots, count),
    cell("g-status", pill), cell("g-join", b));
  return row;
}

for (const b of document.querySelectorAll(".browse-bar .seg button")) {
  b.addEventListener("click", () => {
    browse.show = b.dataset.show;
    browse.shown = GAMES_PAGE;
    for (const o of document.querySelectorAll(".browse-bar .seg button")) {
      o.classList.toggle("on", o === b);
      o.setAttribute("aria-checked", String(o === b));
    }
    renderBrowse();
  });
}
for (const b of document.querySelectorAll(".games-head [data-sort]")) {
  b.addEventListener("click", () => {
    if (browse.sort === b.dataset.sort) browse.desc = !browse.desc;
    else { browse.sort = b.dataset.sort; browse.desc = b.dataset.sort === "players" || b.dataset.sort === "status"; }
    renderBrowse();
  });
}
$("filter-mode").addEventListener("change", () => { browse.mode = $("filter-mode").value; browse.shown = GAMES_PAGE; renderBrowse(); });
$("filter-map").addEventListener("change", () => { browse.map = $("filter-map").value; browse.shown = GAMES_PAGE; renderBrowse(); });
$("browse-search").addEventListener("input", () => { browse.search = $("browse-search").value; browse.shown = GAMES_PAGE; renderBrowse(); });
$("games-more").addEventListener("click", () => { browse.shown += GAMES_PAGE; renderBrowse(); });
$("clear-filters").addEventListener("click", () => {
  Object.assign(browse, { show: "all", mode: "", map: "", search: "", shown: GAMES_PAGE });
  $("browse-search").value = "";
  document.querySelector('.browse-bar .seg [data-show="all"]').click();
});
$("code-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const code = $("browse-code").value.trim().toUpperCase();
  if (/^[A-Z]{4}$/.test(code)) openRoom(code, true);
  else toast("Game codes are 4 letters.", true);
});
$("find").addEventListener("click", () => openBrowse(true));
$("browse-back").addEventListener("click", () => leaveRoom(true));

// Quick match: the busiest public game with a free seat, or a new one with bots
async function quickMatch(button) {
  $("name").dispatchEvent(new Event("change"));
  button.disabled = true;
  try {
    const r = await fetch("/api/quickplay", { method: "POST" });
    const body = await r.json();
    if (!r.ok) toast(body.error || "Couldn't find a match.", true);
    else openRoom(body.room, true);
  } catch (e) {
    toast("Couldn't reach the server. Try again in a moment.", true);
  } finally {
    button.disabled = false;
  }
}
$("quick").addEventListener("click", () => quickMatch($("quick")));
$("empty-quick").addEventListener("click", () => quickMatch($("empty-quick")));

// New game: public or private
async function newGame(isPublic, button) {
  $("name").dispatchEvent(new Event("change"));
  if (button) button.disabled = true;
  try {
    const r = await fetch("/api/rooms", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ public: isPublic }) });
    const body = await r.json();
    if (!r.ok) toast(body.error || "Couldn't create a game.", true);
    else { $("new-dialog").classList.add("hidden"); openRoom(body.room, true); }
  } catch (e) {
    toast("Couldn't create a game. Is the server running?", true);
  } finally {
    if (button) button.disabled = false;
  }
}
$("new-game").addEventListener("click", () => { $("new-dialog").classList.remove("hidden"); $("new-public").focus(); });
$("new-public").addEventListener("click", () => newGame(true, $("new-public")));
$("new-private").addEventListener("click", () => newGame(false, $("new-private")));
$("empty-public").addEventListener("click", () => newGame(true, $("empty-public")));
$("new-cancel").addEventListener("click", () => $("new-dialog").classList.add("hidden"));
$("new-dialog").addEventListener("click", (e) => { if (e.target === $("new-dialog")) $("new-dialog").classList.add("hidden"); });

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
  b.className = "person-btn";
  b.textContent = "⋯";
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
  if (app.results && !$("results").classList.contains("hidden")) showResults(app.results, true);
});
$("report-send").addEventListener("click", () => {
  if (!person) return;
  send({ type: "report_player", id: person.id, reason: $("report-reason").value, note: $("report-note").value });
  $("report-send").disabled = true;
  $("report-send").textContent = "Sent";
});
