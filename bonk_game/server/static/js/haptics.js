// Haptics: little buzzes for what happens to your own ball. On Android
// (Chrome) through navigator.vibrate; in a native app shell (Capacitor,
// for the App Store) through its Haptics plugin. iPhone browsers have no
// vibration, so there it does nothing. Off in Settings (prefs.haptics).

const haptics = {
  last: 0,
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

// Was this near your own ball? (Events give a place, not always who)
function nearMe(x, y, reach = 40) {
  const d = debug.drawn;
  return !!d && performance.now() - d.t < 300 && Math.hypot(d.x - x, d.y - y) < reach;
}
