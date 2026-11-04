// bonk web client: Your stats (the Stats tab of your profile): lifetime totals,
// awards, results by mode and your recent matches, from your profile
// (profileStore in core.js). Signed in, Download my data saves a copy.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

const NAMES = (() => {
  try { return JSON.parse($("bonk-names").textContent); } catch (e) { return { maps: {}, modes: {} }; }
})();
const mapTitle = (id) => NAMES.maps[id] || id;
const modeTitle = (id) => NAMES.modes[id] || id;
const ordinal = (n) => n + (["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) ? 0 : n % 10] || "th");

function whenText(at) {
  const s = Date.now() / 1000 - at;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return new Date(at * 1000).toLocaleDateString();
}

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
  $("stats-since").textContent = s.first_at
    ? `${s.matches} match${s.matches === 1 ? "" : "es"} since ${new Date(s.first_at * 1000).toLocaleDateString()}.`
    : "";
  if (!s.matches) {
    body.append(el("p", "dim", "No matches yet. Play one and it shows up here."));
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

  const awards = Object.entries(s.awards).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  if (awards.length) {
    body.append(el("h3", "", "Awards"));
    const ul = el("ul", "stat-awards");
    for (const [id, n] of awards) {
      const li = el("li", "");
      li.append(el("span", "", AWARD_TITLES[id] || id), el("b", "", `×${n}`));
      ul.append(li);
    }
    body.append(ul);
  }

  body.append(el("h3", "", "By mode"));
  const table = el("table", "stat-modes");
  for (const [id, t] of Object.entries(s.modes).sort((a, b) => b[1].matches - a[1].matches)) {
    const tr = el("tr", "");
    tr.append(el("td", "", modeTitle(id)), el("td", "dim", `${t.matches} played`), el("td", "", `${t.wins} won`));
    table.append(tr);
  }
  body.append(table);

  body.append(el("h3", "", "Recent matches"));
  const ol = el("ol", "stat-history");
  for (const h of p.history) {
    const li = el("li", h.won ? "won" : "");
    const place = h.mode === "teams" ? (h.won ? "Won" : h.place === 1 ? "Draw" : "Lost") : `${ordinal(h.place)} of ${h.of}`;
    const top = el("div", "row-between");
    top.append(el("b", "", place + (h.won ? " · won" : "")), el("span", "dim small", whenText(h.at)));
    const detail = [`${modeTitle(h.mode)} · ${mapTitle(h.map)}`, `${h.kos} KO${h.kos === 1 ? "" : "s"}`];
    if (h.awards.length) detail.push(h.awards.map((a) => AWARD_TITLES[a] || a).join(", "));
    li.append(top, el("div", "dim small", detail.join(" · ")));
    ol.append(li);
  }
  body.append(ol);
}

const AWARD_TITLES = { kos: "Most knockouts", hit: "Hardest hit", falls: "Butterfingers", survivor: "Survivor", pickups: "Power hungry" };


// Signed in: a copy of everything your account keeps (see the privacy page)
$("download-data").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(profileStore.get(), null, 1)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `bonk-my-data-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
