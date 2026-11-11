// bonk web client: Badges (the server's badges.py): goals with levels that
// get harder, worked out from your lifetime stats. Your Stats tab shows
// them all; after a match, the results show the ones you just earned (or
// how close the next one is).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

const BADGES = NAMES.badges || [];  // (stats.js: from the page)
const BADGE_LEVELS = ["bronze", "silver", "gold", "platinum", "diamond"];
const BADGE_LEVEL_TITLES = ["Bronze", "Silver", "Gold", "Platinum", "Diamond"];

// What a badge counts, from your stats (badges.py: value)
function badgeValue(stats, stat) {
  if (stat.startsWith("feats.")) return (stats.feats || {})[stat.slice(6)] || 0;
  if (stat === "maps" || stat === "modes") return Object.values(stats[stat] || {}).filter((t) => t.matches).length;
  if (stat === "awards") return Object.values(stats.awards || {}).reduce((a, b) => a + b, 0);
  return stats[stat] || 0;
}

const badgeLevel = (stats, b) => b.levels.filter((n) => badgeValue(stats, b.stat) >= n).length;

// "Win {n} [match|matches]" for a threshold
function badgeGoal(b, n) {
  return b.goal.replace("{n}", n).replace(/\[([^|\]]*)\|([^\]]*)\]/g, (_, one, many) => (n === 1 ? one : many));
}

// After a match: the badges it took up a level ({badge, level}), and the
// one you're closest to next ({badge, level, have, need}), from your stats
// before and after it
function badgeReport(before, after) {
  const earned = [];
  let next = null;
  for (const b of BADGES) {
    const was = badgeLevel(before, b), now = badgeLevel(after, b);
    if (now > was) earned.push({ badge: b, level: now });
    if (now < b.levels.length && !(b.secret && !now)) {  // (a secret one stays a surprise)
      const have = badgeValue(after, b.stat), need = b.levels[now];
      const from = now ? b.levels[now - 1] : 0;
      const frac = (have - from) / (need - from);
      if (!next || frac > next.frac) next = { badge: b, level: now + 1, have, need, frac };
    }
  }
  return { earned, next };
}

// A badge's medal: its icon on its level's colour (grey until you earn it)
function badgeMedal(b, level, big) {
  const m = document.createElement("span");
  m.className = "badge-medal" + (level ? ` lvl-${BADGE_LEVELS[level - 1]}` : " locked") + (big ? " big" : "");
  m.textContent = b.icon;
  m.setAttribute("aria-hidden", "true");
  return m;
}

const levelName = (level) => BADGE_LEVEL_TITLES[level - 1] || "";

// ---------------------------------------------------------------------------
// Your Stats tab: Up next (the badges closest to their next level), then the
// trophy case (every badge as a medal; pick one to see its goal)
// ---------------------------------------------------------------------------
const UP_NEXT = 4;

// How far a badge is on its way to the next level, or null at its top level
function badgeProgress(stats, b) {
  const lvl = badgeLevel(stats, b);
  if (lvl >= b.levels.length) return null;
  const have = badgeValue(stats, b.stat), need = b.levels[lvl], from = lvl ? b.levels[lvl - 1] : 0;
  return { lvl, have, need, left: need - have, frac: Math.max(0, Math.min(1, (have - from) / (need - from))) };
}

function badgeBar(frac) {
  const bar = document.createElement("div");
  bar.className = "badge-bar";
  const fill = document.createElement("i");
  fill.style.width = `${frac * 100}%`;
  bar.append(fill);
  return bar;
}

function statsSection(title, note) {
  const head = document.createElement("div");
  head.className = "stats-head";
  const h = document.createElement("h3");
  h.textContent = title;
  head.append(h);
  if (note) {
    const n = document.createElement("span");
    n.className = "dim small";
    n.textContent = note;
    head.append(n);
  }
  return head;
}

function renderUpNext(stats, into) {
  const next = BADGES
    .filter((b) => !(b.secret && !badgeLevel(stats, b)))  // (a secret one stays a surprise)
    .map((b) => ({ b, p: badgeProgress(stats, b) }))
    .filter((x) => x.p)
    .sort((x, y) => y.p.frac - x.p.frac || x.p.left - y.p.left)
    .slice(0, UP_NEXT);
  if (!next.length) return;
  const ul = document.createElement("ul");
  ul.className = "up-next";
  for (const { b, p } of next) {
    const li = document.createElement("li");
    const text = document.createElement("div");
    text.className = "badge-text";
    const top = document.createElement("div");
    top.className = "badge-top";
    const title = document.createElement("b");
    title.textContent = b.title + " ";
    const to = document.createElement("span");
    to.className = "dim";
    to.textContent = `→ ${levelName(p.lvl + 1)}`;
    title.append(to);
    const left = document.createElement("span");
    left.className = "up-left";
    left.textContent = `${Math.ceil(p.left)} to go`;
    top.append(title, left);
    const goal = document.createElement("span");
    goal.className = "dim small";
    goal.textContent = `${badgeGoal(b, p.need)} · ${Math.floor(p.have)} / ${p.need}`;
    text.append(top, badgeBar(p.frac), goal);
    li.append(badgeMedal(b, p.lvl), text);
    ul.append(li);
  }
  into.append(statsSection("Up next", "closest to their next level"), ul);
}

function renderTrophyCase(stats, into) {
  const got = BADGES.filter((b) => badgeLevel(stats, b) > 0).length;
  // Earned first (the best first), then the rest, the secret ones last
  const order = BADGES.map((b, k) => ({ b, k, lvl: badgeLevel(stats, b) }))
    .sort((x, y) => (y.lvl - x.lvl) || ((x.b.secret && !x.lvl) - (y.b.secret && !y.lvl)) || x.k - y.k);
  const grid = document.createElement("div");
  grid.className = "trophy-case";
  grid.setAttribute("role", "list");
  const detail = document.createElement("div");
  detail.className = "trophy-detail";
  const show = (b, lvl, button) => {
    for (const t of grid.querySelectorAll(".trophy")) t.classList.toggle("on", t === button);
    detail.innerHTML = "";
    const hidden = b.secret && !lvl;
    const text = document.createElement("div");
    text.className = "badge-text";
    const top = document.createElement("div");
    top.className = "badge-top";
    const title = document.createElement("b");
    title.textContent = hidden ? "???" : b.title;
    const lv = document.createElement("span");
    lv.className = "badge-lvl";
    lv.textContent = lvl ? `${levelName(lvl)}${lvl === b.levels.length ? " · max" : ""}` : "Not yet";
    top.append(title, lv);
    const goal = document.createElement("span");
    goal.className = "dim small";
    const p = badgeProgress(stats, b);
    if (hidden) goal.textContent = "A secret badge. Keep playing to find it";
    else if (p) goal.textContent = `Next: ${badgeGoal(b, p.need)} · ${Math.floor(p.have)} / ${p.need}`;
    else goal.textContent = `${badgeGoal(b, b.levels[lvl - 1])}. That's the top level!`;
    text.append(top, goal);
    if (p && !hidden) text.append(badgeBar(p.frac));
    const medal = hidden ? badgeMedal({ icon: "?" }, 0, true) : badgeMedal(b, lvl, true);
    detail.append(medal, text);
  };
  for (const { b, lvl } of order) {
    const hidden = b.secret && !lvl;
    const t = document.createElement("button");
    t.type = "button";
    t.className = "trophy" + (lvl ? "" : " locked");
    t.setAttribute("role", "listitem");
    t.title = hidden ? "A secret badge" : `${b.title}${lvl ? ` · ${levelName(lvl)}` : ""}`;
    t.setAttribute("aria-label", t.title);
    const name = document.createElement("span");
    name.className = "trophy-name";
    name.textContent = hidden ? "???" : b.title;
    t.append(hidden ? badgeMedal({ icon: "?" }, 0) : badgeMedal(b, lvl), name);
    t.addEventListener("click", () => show(b, lvl, t));
    grid.append(t);
  }
  const hint = document.createElement("p");
  hint.className = "dim small trophy-hint";
  hint.textContent = "Pick a badge to see its goal.";
  detail.append(hint);
  into.append(statsSection(`Trophy case · ${got} of ${BADGES.length}`, "pick one for its goal"), grid, detail);
}

// ---------------------------------------------------------------------------
// The results screen: the badges you just earned (results.js)
// ---------------------------------------------------------------------------
function renderEarned(report) {
  const box = $("badges-earned");
  box.innerHTML = "";
  box.classList.toggle("hidden", !report);
  if (!report) return;
  if (report.earned.length) {
    const h = document.createElement("div");
    h.className = "badges-earned-head";
    h.textContent = report.earned.length === 1 ? "Badge earned!" : `${report.earned.length} badges earned!`;
    box.append(h);
    const ul = document.createElement("ul");
    ul.className = "earned-list";
    report.earned.forEach(({ badge, level }, k) => {
      const li = document.createElement("li");
      li.style.animationDelay = `${0.25 + k * 0.15}s`;
      const t = document.createElement("span");
      t.className = "earned-text";
      const name = document.createElement("b");
      name.textContent = `${badge.title} · ${levelName(level)}`;
      const what = document.createElement("span");
      what.className = "dim small";
      what.textContent = badgeGoal(badge, badge.levels[level - 1]);
      t.append(name, what);
      li.append(badgeMedal(badge, level, true), t);
      ul.append(li);
    });
    box.append(ul);
  }
  if (report.next) {
    const { badge, level, have, need } = report.next;
    const p = document.createElement("p");
    p.className = "badge-next dim small";
    p.append(badgeMedal(badge, 0));
    p.append(` Next: ${badge.title} ${levelName(level)}. ${badgeGoal(badge, need)} (${Math.floor(have)}/${need})`);
    box.append(p);
  }
}
