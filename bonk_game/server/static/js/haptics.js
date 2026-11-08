// Haptics: a soft tick when you tap a button in the menus, and little
// buzzes for what happens to your own ball. On Android
// (Chrome) through navigator.vibrate; in a native app shell (Capacitor,
// for the App Store) through its Haptics plugin. iPhone browsers have no
// vibration, so there it does nothing. Off in Settings (prefs.haptics).

const haptics = {
  last: 0,
  lastTick: 0,
  // The menus: the lightest tick there is, for a tap on a button
  tick() {
    if (prefs.haptics === false || !this.supported()) return;
    const now = performance.now();
    if (now - this.lastTick < 40) return;
    this.lastTick = now;
    const native = this.native();
    try {
      if (native) native.impact({ style: "LIGHT" });
      else navigator.vibrate(6);
    } catch (e) { /* not allowed yet: skip */ }
  },
  native() { return window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Haptics; },
  // (Desktop Chrome has navigator.vibrate too, doing nothing: phones and tablets only)
  supported() {
    return !!this.native() || (typeof navigator.vibrate === "function" && matchMedia("(pointer: coarse)").matches);
  },
  // kind: "tap" (light), "bump" (by strength), "hit" (medium), "big" (heavy), or a pattern of ms
  buzz(kind, strength = 1) {
    if (prefs.haptics === false || document.hidden) return;
    const now = performance.now();
    const important = kind === "big" || Array.isArray(kind);
    if (!important && now - this.last < 90) return;  // (bumps come in bunches)
    this.last = now;
    const native = this.native();
    try {
      if (native) {
        if (Array.isArray(kind)) native.vibrate({ duration: kind.reduce((a, b) => a + b, 0) });
        else native.impact({ style: kind === "big" ? "HEAVY" : kind === "hit" || strength > 0.6 ? "MEDIUM" : "LIGHT" });
        return;
      }
      if (!this.supported()) return;
      if (Array.isArray(kind)) navigator.vibrate(kind);
      else navigator.vibrate({ tap: 12, bump: Math.round(10 + 22 * clamp(strength, 0, 1)), hit: 35, big: 70 }[kind] || 15);
    } catch (e) { /* not allowed (no tap on the page yet): skip */ }
  },
};

// Taps on anything clickable in the menus (buttons, chips, swatches,
// toggles, links that act as buttons). Not the touch controls over the game:
// the heavy button has its own (input.js), and the joystick none.
const TICKS = "button, [role=button], .swatch, label.check, select, input[type=checkbox], input[type=radio], summary";
document.addEventListener("click", (e) => {
  const el = e.target.closest && e.target.closest(TICKS);
  if (!el || el.disabled || el.closest("#touch")) return;
  haptics.tick();
}, true);

// Was this near your own ball? (Events give a place, not always who)
function nearMe(x, y, reach = 40) {
  const d = debug.drawn;
  return !!d && performance.now() - d.t < 300 && Math.hypot(d.x - x, d.y - y) < reach;
}
