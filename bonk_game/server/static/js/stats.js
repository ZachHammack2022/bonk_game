// bonk web client: Your stats (the Stats tab of your profile): your rating,
// four headline numbers, the badges you're closest to (Up next) and every
// badge (the trophy case), from your profile (profileStore in core.js).
// Signed in, Download my data saves a copy.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

const NAMES = (() => {
  try { return JSON.parse($("bonk-names").textContent); } catch (e) { return { maps: {}, modes: {} }; }
})();

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// Best map: the best win rate over at least BEST_MAP_MATCHES matches on it
const BEST_MAP_MATCHES = 10;

function renderStats() {
  const p = profileStore.get();
  const s = p.stats;
  const body = $("stats-body");
  body.innerHTML = "";
  renderMyRating();  // (rating.js)
  $("stats-since").textContent = s.first_at
    ? `${s.matches} match${s.matches === 1 ? "" : "es"} since ${new Date(s.first_at * 1000).toLocaleDateString()}.`
    : "";
  if (!s.matches) {
    body.append(el("p", "dim", "No matches yet. Play one and your numbers show up here."));
  } else {
    // Four headline numbers. (Totals like knockouts, falls and power-ups
    // are on their badges: Bonker, Butterfingers, Power Hungry)
    const tiles = el("div", "stat-tiles");
    const tile = (value, label, sub, long) => {
      const t = el("div", "stat-tile" + (long ? " long" : ""));
      t.append(el("b", "", value), el("span", "stat-label", label), el("span", "dim small", sub));
      tiles.append(t);
    };
    tile(`${Math.round((100 * s.wins) / s.matches)}%`, "Win rate", `${s.wins} of ${s.matches}`);
    tile((s.kos / s.matches).toFixed(1), "Knockouts a match", `${s.kos} in all`);
    tile(s.deaths ? (s.kos / s.deaths).toFixed(2) : String(s.kos), "Bonk ratio",
      s.deaths ? `${s.kos} out · ${s.deaths} in` : "never knocked out!");
    const best = Object.entries(s.maps || {})
      .filter(([, m]) => m.matches >= BEST_MAP_MATCHES)
      .sort(([, a], [, b]) => b.wins / b.matches - a.wins / a.matches || b.matches - a.matches)[0];
    if (best) {
      const [id, m] = best;
      tile(NAMES.maps[id] || id, "Best map", `${Math.round((100 * m.wins) / m.matches)}% wins · ${m.matches} played`, true);
    } else {
      tile("–", "Best map", `play ${BEST_MAP_MATCHES} on one map`);
    }
    tiles.querySelectorAll(".stat-tile")[2].title = "Knockouts you made for each time you were knocked out";
    body.append(tiles);
  }
  renderUpNext(s, body);      // (badges.js)
  renderTrophyCase(s, body);
}

// Signed in: a copy of everything your account keeps (see the privacy page)
$("download-data").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(profileStore.get(), null, 1)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `bonk-my-data-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
