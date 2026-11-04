// bonk web client: Other people. The home page's public rooms and Quick play
// (#35); muting someone on your screen, and reporting them (#36).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Public rooms and Quick play
// ---------------------------------------------------------------------------
const PUBLIC_EVERY = 5000;  // ms between looking at the list again
let publicTimer = null;

// The list stays up to date while the home page is showing
function watchPublic(on) {
  clearInterval(publicTimer);
  publicTimer = on ? setInterval(refreshPublic, PUBLIC_EVERY) : null;
  if (on) refreshPublic();
}

async function refreshPublic() {
  try {
    const r = await fetch("/api/public");
    if (r.ok && !$("home").classList.contains("hidden")) renderPublic((await r.json()).rooms);
  } catch (e) { /* offline or restarting: next time */ }
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function renderPublic(rooms) {
  $("public").classList.toggle("hidden", !rooms.length);
  const ul = $("public-list");
  ul.innerHTML = "";
  for (const r of rooms) {
    const li = document.createElement("li");
    const info = document.createElement("span");
    info.className = "public-info";
    const title = document.createElement("b");
    title.textContent = `${r.mode} · ${r.map}`;
    const sub = document.createElement("span");
    sub.className = "dim small";
    sub.textContent = (r.people === 1 ? "1 person" : `${r.people} people`) + (r.bots ? ` + ${plural(r.bots, "bot")}` : "") +
      (r.playing ? " · match on" : " · in the lobby") + (r.host ? ` · ${r.host}'s room` : "");
    info.append(title, sub);
    const b = document.createElement("button");
    b.textContent = r.people >= r.most ? "Watch" : "Join";
    b.setAttribute("aria-label", `${b.textContent}: ${title.textContent}`);
    b.addEventListener("click", () => { $("name").dispatchEvent(new Event("change")); openRoom(r.room, true); });
    li.append(info, b);
    ul.appendChild(li);
  }
}

$("quick").addEventListener("click", async () => {
  $("name").dispatchEvent(new Event("change"));
  $("quick").disabled = true;
  try {
    const r = await fetch("/api/quickplay", { method: "POST" });
    const body = await r.json();
    if (!r.ok) toast(body.error || "Couldn't find a match.", true);
    else openRoom(body.room, true);
  } catch (e) {
    toast("Couldn't reach the server. Try again in a moment.", true);
  } finally {
    $("quick").disabled = false;
  }
});

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
