// Your profile: name, ball, settings, lifetime stats and recent matches.
// Saved in this browser for now (js/core.js: profileStore); the same shape,
// with the same rules (bonk_game/server/profiles.py), is what an account
// will hold, so a browser's profile can be attached to an account later.
//
//   { format: "bonk-profile", v: 1,
//     id: "<random>",           this browser's profile (not the room token)
//     merged: ["<id>", ...],    other profiles already added in (merge)
//     name, color, own_color, pattern, trail, hat, ko, muted,
//                               (own_color: "#rrggbb" or null; accounts only)
//     prefs: { volume, shake, ping, keys: {...} },
//     stats: { matches, wins, kos, falls, deaths, pickups, best_hit,
//              awards: { kos: 3, ... }, modes: { ffa: { matches, wins } },
//              maps: { platform: { matches, wins } }, first_at, last_at },
//     history: [ newest first, up to HISTORY entries:
//       { id, at, mode, map, place, of, won, score, kos, falls, deaths,
//         best_hit, pickups, awards: ["kos", ...], players, people } ] }
//
// An exported file is the profile itself. Times are seconds since 1970.
//
// Used by js/core.js and js/stats.js in the browser and by tests in Node.
(function (root) {
  "use strict";

  const FORMAT = "bonk-profile";
  const VERSION = 1;
  const HISTORY = 50;
  const COUNTS = ["matches", "wins", "kos", "falls", "deaths", "pickups"];
  const ENTRY_COUNTS = ["place", "of", "kos", "falls", "deaths", "pickups", "players", "people"];
  const MAX = 1e9;
  const TIME = 1e11;  // seconds since 1970: plenty

  const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const int = (v, lo = 0, hi = MAX) => (Number.isFinite(v) ? Math.max(lo, Math.min(hi, Math.trunc(v))) : lo);
  const num = (v) => (Number.isFinite(v) ? Math.max(0, Math.min(MAX, Math.round(v * 10) / 10)) : 0);
  const text = (v, n) => (typeof v === "string" ? v.slice(0, n) : "");
  const key = (v) => typeof v === "string" && /^[a-z0-9_-]{1,24}$/.test(v);

  function empty(id) {
    return {
      format: FORMAT, v: VERSION, id, merged: [],
      name: "", color: null, own_color: null, pattern: "plain", trail: "none", hat: "none", ko: "pop", muted: false,
      prefs: {},
      stats: { matches: 0, wins: 0, kos: 0, falls: 0, deaths: 0, pickups: 0, best_hit: 0,
               awards: {}, modes: {}, maps: {}, first_at: null, last_at: null },
      history: [],
    };
  }

  function cleanTally(t) {
    const out = {};
    if (!isObj(t)) return out;
    for (const k of Object.keys(t).sort().slice(0, 50)) {
      if (key(k) && isObj(t[k])) out[k] = { matches: int(t[k].matches), wins: int(t[k].wins) };
    }
    return out;
  }

  function cleanEntry(e) {
    if (!isObj(e) || !text(e.id, 40)) return null;
    const out = { id: text(e.id, 40), at: int(e.at, 0, TIME), mode: key(e.mode) ? e.mode : "?",
                  map: key(e.map) ? e.map : "?", won: e.won === true, score: num(e.score) };
    for (const k of ENTRY_COUNTS) out[k] = int(e[k], 0, 1000);
    out.best_hit = num(e.best_hit);
    out.awards = Array.isArray(e.awards) ? e.awards.filter(key).slice(0, 10) : [];
    return out;
  }

  // Any object (a file, an old save) as a valid profile, or null
  function validate(p, prefsCheck) {
    if (!isObj(p) || p.format !== FORMAT || !text(p.id, 40)) return null;
    const out = empty(text(p.id, 40));
    out.merged = Array.isArray(p.merged) ? p.merged.filter((x) => text(x, 40) === x && x).slice(0, 100) : [];
    out.name = text(p.name, 16);
    out.color = Number.isInteger(p.color) && p.color >= 0 && p.color < 10 ? p.color : null;
    out.own_color = typeof p.own_color === "string" && /^#[0-9a-f]{6}$/.test(p.own_color) ? p.own_color : null;
    out.pattern = text(p.pattern, 16) || "plain";
    out.trail = text(p.trail, 16) || "none";
    out.hat = text(p.hat, 16) || "none";
    out.ko = text(p.ko, 16) || "pop";
    out.muted = p.muted === true;
    out.prefs = prefsCheck ? prefsCheck(isObj(p.prefs) ? p.prefs : {}) : (isObj(p.prefs) ? p.prefs : {});
    const s = isObj(p.stats) ? p.stats : {};
    for (const k of COUNTS) out.stats[k] = int(s[k]);
    out.stats.best_hit = num(s.best_hit);
    out.stats.awards = {};
    if (isObj(s.awards)) for (const k of Object.keys(s.awards).sort().slice(0, 20)) if (key(k)) out.stats.awards[k] = int(s.awards[k]);
    out.stats.modes = cleanTally(s.modes);
    out.stats.maps = cleanTally(s.maps);
    out.stats.first_at = Number.isFinite(s.first_at) ? int(s.first_at, 0, TIME) : null;
    out.stats.last_at = Number.isFinite(s.last_at) ? int(s.last_at, 0, TIME) : null;
    const seen = new Set();
    out.history = (Array.isArray(p.history) ? p.history : []).map(cleanEntry)
      .filter((e) => e && !seen.has(e.id) && seen.add(e.id)).slice(0, HISTORY);
    return out;
  }

  const tally = (t, k, won) => {
    const cur = t[k] || { matches: 0, wins: 0 };
    return { ...t, [k]: { matches: cur.matches + 1, wins: cur.wins + (won ? 1 : 0) } };
  };

  // The profile after one more match (a history entry; see the top).
  // The same match twice (say, after a reconnect) only counts once.
  function record(p, entry) {
    const e = cleanEntry(entry);
    if (!e || p.history.some((h) => h.id === e.id)) return p;
    const s = p.stats;
    const awards = { ...s.awards };
    for (const a of e.awards) awards[a] = (awards[a] || 0) + 1;
    return {
      ...p,
      stats: {
        ...s,
        matches: s.matches + 1, wins: s.wins + (e.won ? 1 : 0), kos: s.kos + e.kos, falls: s.falls + e.falls,
        deaths: s.deaths + e.deaths, pickups: s.pickups + e.pickups, best_hit: Math.max(s.best_hit, e.best_hit),
        awards, modes: tally(s.modes, e.mode, e.won), maps: tally(s.maps, e.map, e.won),
        first_at: s.first_at === null ? e.at : Math.min(s.first_at, e.at), last_at: Math.max(s.last_at || 0, e.at),
      },
      history: [e, ...p.history].slice(0, HISTORY),
    };
  }

  function addTallies(a, b) {
    const out = { ...a };
    for (const k of Object.keys(b)) {
      const x = out[k] || { matches: 0, wins: 0 };
      out[k] = { matches: x.matches + b[k].matches, wins: x.wins + b[k].wins };
    }
    return out;
  }

  // Two profiles as one (another device's, or a browser's into an account):
  // totals add up, recent matches interleave. `a` keeps its name, ball and
  // settings. Adding the same profile twice doesn't count it twice.
  function merge(a, b) {
    if (a.id === b.id) return b.stats.matches > a.stats.matches ? { ...b } : a;
    if (a.merged.includes(b.id)) return a;
    const s = a.stats, t = b.stats;
    const stats = { ...s, best_hit: Math.max(s.best_hit, t.best_hit) };
    for (const k of COUNTS) stats[k] = s[k] + t[k];
    stats.awards = { ...s.awards };
    for (const k of Object.keys(t.awards)) stats.awards[k] = (stats.awards[k] || 0) + t.awards[k];
    stats.modes = addTallies(s.modes, t.modes);
    stats.maps = addTallies(s.maps, t.maps);
    const firsts = [s.first_at, t.first_at].filter((x) => x !== null);
    stats.first_at = firsts.length ? Math.min(...firsts) : null;
    const lasts = [s.last_at, t.last_at].filter((x) => x !== null);
    stats.last_at = lasts.length ? Math.max(...lasts) : null;
    const seen = new Set();
    const history = [...a.history, ...b.history]
      .filter((e) => !seen.has(e.id) && seen.add(e.id))
      .sort((x, y) => y.at - x.at || (x.id < y.id ? -1 : x.id > y.id ? 1 : 0))
      .slice(0, HISTORY);
    const merged = [...new Set([...a.merged, b.id, ...b.merged])].filter((x) => x !== a.id).slice(0, 100);
    return { ...a, merged, stats, history };
  }

  const api = { FORMAT, VERSION, HISTORY, empty, validate, record, merge };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BonkProfile = api;
})(typeof window !== "undefined" ? window : this);
