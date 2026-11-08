// bonk web client: Keyboard, gamepad and touch input, and emotes.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Input: WASD (or your keys) or arrows, Space/Shift for heavy; a joystick
// and a heavy button on touch screens
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
  if (e.code === "Escape" && !$("game-settings").classList.contains("hidden")) { closeGameSettings(); return; }
  if (e.code === "Escape" && !e.target.matches("input")) { openSettings(); return; }
  // Typing (chat, names): not game keys
  if (e.target.matches("input, textarea, select")) return;
  if (e.code === "KeyM") { sound.toggle(); return; }
  // Chat during a match (chat.js)
  if ((e.code === "Enter" || e.code === "KeyT") && !(e.code in KEYMAP) && app.match && !$("game").classList.contains("hidden")) {
    e.preventDefault();
    openGameChat();
    return;
  }
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

// Touch: a joystick on the left half of the screen and heavy on the right.
// The joystick starts wherever your thumb lands (so you don't have to find
// it), and you steer by dragging from there: left/right past a small dead
// zone, up further to jump (fly, on Classic), down to push down. Each half
// follows its own finger, so you can move and go heavy at once.
const STICK_RANGE = 48;  // px from the centre the knob can go
const touchStick = { id: null, x0: 0, y0: 0 };
const touchHeavy = { id: null };

function stickButtons(dx, dy) {
  const r = STICK_RANGE;
  return [dy < -0.55 * r ? 1 : 0, dx < -0.3 * r ? 1 : 0, dy > 0.55 * r ? 1 : 0, dx > 0.3 * r ? 1 : 0];
}

function setTouch(b) {
  if (b.some((v, k) => v !== held.touch[k])) { held.touch = b; sendInput(); }
}

function initTouch() {
  document.body.classList.add("touch");
  $("touch").classList.remove("hidden");
  const zone = $("move-zone"), stick = $("stick"), knob = stick.querySelector(".knob");
  const place = (x, y) => {
    // (in the zone's own coordinates; null puts it back where it rests)
    stick.style.left = x === null ? "" : `${x}px`;
    stick.style.top = y === null ? "" : `${y}px`;
  };
  zone.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    if (touchStick.id !== null) return;
    sound.unlock();
    zone.setPointerCapture(e.pointerId);
    const box = zone.getBoundingClientRect();
    touchStick.id = e.pointerId; touchStick.x0 = e.clientX; touchStick.y0 = e.clientY;
    place(e.clientX - box.left, e.clientY - box.top);
    stick.classList.add("active");
  });
  zone.addEventListener("pointermove", (e) => {
    if (e.pointerId !== touchStick.id) return;
    e.preventDefault();
    const dx = e.clientX - touchStick.x0, dy = e.clientY - touchStick.y0;
    const d = Math.hypot(dx, dy), k = d > STICK_RANGE ? STICK_RANGE / d : 1;
    knob.style.transform = `translate(${dx * k}px, ${dy * k}px)`;
    const b = stickButtons(dx, dy);
    setTouch([b[0], b[1], b[2], b[3], held.touch[4]]);
  });
  const stickUp = (e) => {
    if (e.pointerId !== touchStick.id) return;
    touchStick.id = null;
    knob.style.transform = "";
    stick.classList.remove("active");
    place(null, null);
    setTouch([0, 0, 0, 0, held.touch[4]]);
  };
  zone.addEventListener("pointerup", stickUp);
  zone.addEventListener("pointercancel", stickUp);

  const hz = $("heavy-zone"), hb = $("heavy-btn");
  hz.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    if (touchHeavy.id !== null) return;
    sound.unlock();
    hz.setPointerCapture(e.pointerId);
    touchHeavy.id = e.pointerId;
    hb.classList.add("down");
    haptics.tick();  // a touch screen button you can feel
    setTouch([...held.touch.slice(0, 4), 1]);
  });
  const heavyUp = (e) => {
    if (e.pointerId !== touchHeavy.id) return;
    touchHeavy.id = null;
    hb.classList.remove("down");
    setTouch([...held.touch.slice(0, 4), 0]);
  };
  hz.addEventListener("pointerup", heavyUp);
  hz.addEventListener("pointercancel", heavyUp);

  // Only while you're playing: not over the results, a replay or the killcam
  // (which you tap to skip)
  const sync = () => {
    requestAnimationFrame(sync);
    const off = !playing() || replayer.active;
    if (off !== $("touch").classList.contains("off")) {
      $("touch").classList.toggle("off", off);
      if (off) { stickUp({ pointerId: touchStick.id }); heavyUp({ pointerId: touchHeavy.id }); }
    }
  };
  requestAnimationFrame(sync);  // (once every script has loaded: replayer is in replay.js)
}
if ("ontouchstart" in window || navigator.maxTouchPoints > 0) initTouch();

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
  toast("Controller connected");
  if (settingsOpen()) renderSettings();
});
window.addEventListener("gamepaddisconnected", () => {
  gamepad.name = null;
  toast("Controller disconnected");
  if (settingsOpen()) renderSettings();
});
