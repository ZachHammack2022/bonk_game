// bonk web client: Your stats (the Stats tab of your profile): your rating,
// lifetime totals and badges, from your profile (profileStore in core.js).
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
    body.append(el("p", "dim", "No matches yet. Play one and it shows up here."));
    renderBadges(s, body);  // (badges.js: all still to earn)
    return;
  }
  const tiles = el("div", "stat-tiles");
  const tile = (value, label) => {
    const t = el("div", "stat-tile");
    t.append(el("b", "", value), el("span", "dim small", label));
    tiles.append(t);
  };
  tile(s.wins, `wins (${Math.round((100 * s.wins) / s.matches)}%)`);
  tile(s.kos, "knockouts");
  tile((s.kos / s.matches).toFixed(1), "knockouts a match");
  tile(s.deaths, "times knocked out");
  tile(s.falls, "falls");
  tile(Math.round(s.best_hit), "hardest hit");
  body.append(tiles);
  renderBadges(s, body);  // (badges.js)
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
