// Rebuilding the full state from the server's "delta" messages (see
// bonk_game/server/delta.py for the format). Never changes the state it
// starts from: the drawing code still blends between the last two.
//
// Used by js/core.js in the browser and by tests in Node.
(function (root) {
  "use strict";

  const RESERVED = new Set(["type", "base", "gone"]);
  const isPatch = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

  // The full state after `d`, or null if `d` doesn't build on `prev`
  // (then wait for the next full state)
  function apply(prev, d) {
    const base = d.base ?? d.tick - 1;
    if (!prev || prev.tick !== base) return null;
    const s = { ...prev, type: "state", events: [] };
    for (const k of d.gone || []) delete s[k];
    for (const k in d) {
      if (RESERVED.has(k)) continue;
      const v = d[k];
      if (Array.isArray(s[k]) && isPatch(v)) {
        const items = s[k].slice();
        for (const i in v) {
          const old = items[+i];
          // A level shape sends only its changed keys
          items[+i] = isPatch(old) ? { ...old, ...v[i] } : v[i];
        }
        s[k] = items;
      } else {
        s[k] = v;
      }
    }
    return s;
  }

  const api = { apply };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BonkDelta = api;
})(typeof window !== "undefined" ? window : this);
