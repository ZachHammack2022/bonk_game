// bonk web client: The settings menu (⚙ or Esc): sound, screen shake, ping, colourblind mode and controls.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

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
const RESERVED_KEYS = new Set(["Digit1", "Digit2", "Digit3", "Digit4", "KeyM", "KeyT", "Escape", "Tab", "Enter"]);

const prefs = (() => {
  const d = { volume: 0.8, music: 0.5, shake: true, haptics: true, ping: true, predictOthers: true, chat: true, colorblind: false, contrast: false, keys: { ...DEFAULT_KEYS } };
  const saved = profileStore.get().prefs;
  return { ...d, ...saved, keys: { ...d.keys, ...(saved.keys || {}) } };
})();
const savePrefs = () => profileStore.update((p) => ({ ...p, prefs: JSON.parse(JSON.stringify(prefs)) }));

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

// ---------------------------------------------------------------------------
// Your profile: one page, the same from everywhere, with tabs for your ball,
// your stats and your settings, and signing in at the bottom. The Profile
// button (start page, game list) opens it on your ball; the gear and Esc (in
// a room) open it on Settings.
// ---------------------------------------------------------------------------
const ME_PANES = { ball: "profile", stats: "stats", settings: "settings" };
let meTab = "ball";

function showMeTab(tab) {
  meTab = tab;
  menu.capture = null;
  for (const b of document.querySelectorAll("#me-tabs button")) {
    const on = b.dataset.tab === tab;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on);
  }
  for (const [t, id] of Object.entries(ME_PANES)) $(id).classList.toggle("hidden", t !== tab);
  if (tab === "ball") renderProfileEditor();         // (lobby.js)
  else if (tab === "stats") renderStats();           // (stats.js)
  else { renderSettings(); renderPeople(); }         // (people.js)
}
function openMe(tab) {
  showMeTab(tab || meTab);
  renderMeHead();
  $("me").classList.remove("hidden");
  held.keys.clear(); sendInput();
}
function closeMe() {
  menu.capture = null;
  $("me").classList.add("hidden");
}
const meOpen = () => !$("me").classList.contains("hidden");
// Its header, and the Profile buttons: your ball and your name
function renderMeHead() {
  const name = (me.name || "").trim() || "Player";
  $("me-name").textContent = profileStore.user ? `${name} · signed in` : `${name} · guest`;
  $("me-ball").replaceChildren(ballCanvas(40, me.ballHex, me.pattern, me.look("hat")));  // (lobby.js)
  for (const el of document.querySelectorAll(".me-button-ball")) {
    el.replaceChildren(ballCanvas(22, me.ballHex, me.pattern, "none"));
  }
}

const openSettings = () => openMe("settings");
const closeSettings = closeMe;
const settingsOpen = meOpen;

function renderSettings() {
  $("set-volume").value = Math.round(prefs.volume * 100);
  $("set-volume-out").textContent = sound.muted ? "muted" : `${Math.round(prefs.volume * 100)}%`;
  $("set-music").value = Math.round(prefs.music * 100);
  $("set-music-out").textContent = sound.muted ? "muted" : prefs.music ? `${Math.round(prefs.music * 100)}%` : "off";
  $("set-mute").checked = sound.muted;
  $("set-shake").checked = prefs.shake;
  $("set-haptics").checked = prefs.haptics !== false;
  $("set-haptics-row").classList.toggle("hidden", !haptics.supported());
  $("set-ping").checked = prefs.ping;
  $("set-predict").checked = prefs.predictOthers !== false;
  $("set-chat").checked = prefs.chat !== false;
  $("set-colorblind").checked = prefs.colorblind;
  $("set-contrast").checked = prefs.contrast;
  const pad = typeof gamepad !== "undefined" && gamepad.name;
  $("set-pad").textContent = pad
    ? `${pad.replace(/\s*\(.*\)\s*$/, "").slice(0, 40)}: stick or d-pad to move, A jump, B/X/bumpers/triggers heavy, Y wave, Start for this menu.`
    : "Plug in a controller (or press a button on one) to play with it.";
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
  if (document.body.classList.contains("touch")) {
    $("controls-help").textContent = "Touch the left half of the screen and drag to move (push up to jump); touch the right half to go heavy.";
    return;
  }
  $("controls-help").textContent = `Move with ${moves} or the arrow keys. ${keyName(k.heavy)} or Shift goes heavy. 1–4 for emotes. Esc for settings.`;
}

for (const id of ["open-settings-lobby", "open-settings-game"]) {
  $(id).addEventListener("click", (e) => { e.currentTarget.blur(); openSettings(); });
}
for (const b of document.querySelectorAll(".me-button")) {
  b.addEventListener("click", (e) => { e.currentTarget.blur(); openMe(b.dataset.me); });
}
for (const b of document.querySelectorAll("#me-tabs button")) b.addEventListener("click", () => showMeTab(b.dataset.tab));
$("me-close").addEventListener("click", closeMe);
$("me-done").addEventListener("click", closeMe);
$("me").addEventListener("click", (e) => { if (e.target === $("me")) closeMe(); });
$("set-volume").addEventListener("input", () => {
  prefs.volume = +$("set-volume").value / 100;
  if (sound.muted && prefs.volume > 0) sound.setMuted(false);
  savePrefs(); renderSettings();
});
$("set-volume").addEventListener("change", () => sound.play("point"));
$("set-volume").addEventListener("input", () => music.volume());
// Music: a share of the main volume (music.js)
$("set-music").addEventListener("input", () => {
  prefs.music = +$("set-music").value / 100;
  savePrefs(); renderSettings(); music.volume();
});
$("set-mute").addEventListener("change", () => { sound.setMuted($("set-mute").checked); renderSettings(); });
$("set-shake").addEventListener("change", () => { prefs.shake = $("set-shake").checked; savePrefs(); });
$("set-haptics").addEventListener("change", () => {
  prefs.haptics = $("set-haptics").checked; savePrefs();
  if (prefs.haptics) haptics.buzz("hit");  // feel what it's like
});
$("set-ping").addEventListener("change", () => { prefs.ping = $("set-ping").checked; savePrefs(); });
$("set-predict").addEventListener("change", () => { prefs.predictOthers = $("set-predict").checked; savePrefs(); });
$("set-chat").addEventListener("change", () => { prefs.chat = $("set-chat").checked; savePrefs(); chat.renderFeed(); });
for (const [id, key] of [["set-colorblind", "colorblind"], ["set-contrast", "contrast"]]) {
  $(id).addEventListener("change", () => { prefs[key] = $(id).checked; savePrefs(); applyLooks(app.match); });
}
$("set-reset-keys").addEventListener("click", () => {
  prefs.keys = { ...DEFAULT_KEYS }; menu.capture = null;
  savePrefs(); buildKeymap(); renderSettings(); updateHelp();
});
