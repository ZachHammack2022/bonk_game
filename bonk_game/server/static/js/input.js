// bonk web client: Keyboard, gamepad and touch input, and emotes.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Input: WASD (or your keys) or arrows, Space/Shift for heavy; touch buttons
// on phones
// ---------------------------------------------------------------------------
const held = { keys: new Set(), touch: [0, 0, 0, 0, 0], pad: [0, 0, 0, 0, 0] };
let lastSent = "";

function buttons() {
  const b = [0, 0, 0, 0, 0];
  for (const code of held.keys) b[KEYMAP[code]] = 1;
  held.touch.forEach((v, i) => { if (v) b[i] = 1; });
  held.pad.forEach((v, i) => { if (v) b[i] = 1; });
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
  // Always let go, even of a key that was rebound while it was held
  if (!held.keys.delete(e.code)) return;
  sendInput();
});
window.addEventListener("blur", () => { held.keys.clear(); held.touch.fill(0); held.pad.fill(0); sendInput(); });
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
// Gamepads (any controller the browser maps to the "standard" layout: Xbox,
// PlayStation, Switch Pro and most others). Polled every frame.
//   move: left stick or d-pad     jump: A (or d-pad / stick up)
//   heavy: B, X, a bumper or a trigger     Y: wave     Start: settings
//   on the results screen, A votes to play again
// ---------------------------------------------------------------------------
const PAD = {
  A: 0, B: 1, X: 2, Y: 3, LB: 4, RB: 5, LT: 6, RT: 7, START: 9,
  UP: 12, DOWN: 13, LEFT: 14, RIGHT: 15,
};
const STICK = 0.5, STICK_UP = 0.75;  // how far the stick has to go (up is stiffer, so jumps are on purpose)
const gamepad = { prev: new Set(), name: null };

function padState(p) {
  const on = (i) => { const b = p.buttons[i]; return !!b && (b.pressed || b.value > 0.5); };
  const x = p.axes[0] || 0, y = p.axes[1] || 0;
  const move = [
    on(PAD.A) || on(PAD.UP) || y < -STICK_UP,
    on(PAD.LEFT) || x < -STICK,
    on(PAD.DOWN) || y > STICK,
    on(PAD.RIGHT) || x > STICK,
    on(PAD.B) || on(PAD.X) || on(PAD.LB) || on(PAD.RB) || on(PAD.LT) || on(PAD.RT),
  ].map(Number);
  const pressed = new Set(p.buttons.map((b, i) => (on(i) ? i : -1)).filter((i) => i >= 0));
  return { move, pressed };
}

function pollGamepads() {
  requestAnimationFrame(pollGamepads);
  const pads = navigator.getGamepads ? [...navigator.getGamepads()].filter(Boolean) : [];
  if (!pads.length) {
    if (held.pad.some(Boolean)) { held.pad.fill(0); sendInput(); }
    gamepad.prev = new Set();
    return;
  }
  // Every connected pad counts (handy when one is a wheel or a stray device)
  const move = [0, 0, 0, 0, 0], pressed = new Set();
  for (const p of pads) {
    const s = padState(p);
    s.move.forEach((v, i) => { if (v) move[i] = 1; });
    s.pressed.forEach((i) => pressed.add(i));
  }
  const before = gamepad.prev;
  const tapped = (i) => pressed.has(i) && !before.has(i);  // just pressed this frame
  gamepad.prev = pressed;

  if (tapped(PAD.START)) { settingsOpen() ? closeSettings() : openSettings(); return; }
  if (settingsOpen()) {
    if (held.pad.some(Boolean)) { held.pad.fill(0); sendInput(); }
    return;
  }
  if (app.results && !$("results").classList.contains("hidden") && tapped(PAD.A)) { $("vote").click(); return; }
  if (playing() && tapped(PAD.Y)) sendEmote(0);

  const next = playing() ? move : [0, 0, 0, 0, 0];
  if (next.join("") !== held.pad.join("")) {
    held.pad = next;
    sendInput();
  }
}
requestAnimationFrame(pollGamepads);

window.addEventListener("gamepadconnected", (e) => {
  gamepad.name = e.gamepad.id;
  toast("🎮 Controller connected");
  if (settingsOpen()) renderSettings();
});
window.addEventListener("gamepaddisconnected", () => {
  gamepad.name = null;
  toast("🎮 Controller disconnected");
  if (settingsOpen()) renderSettings();
});
