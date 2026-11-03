// bonk web client: Keyboard and touch input, and emotes.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

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
  // Always let go, even of a key that was rebound while it was held
  if (!held.keys.delete(e.code)) return;
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
