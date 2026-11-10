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

// A secret badge you haven't found yet
function secretCard() {
  const li = document.createElement("li");
  li.className = "badge-card locked secret";
  const m = document.createElement("span");
  m.className = "badge-medal locked";
  m.textContent = "?";
  m.setAttribute("aria-hidden", "true");
  const text = document.createElement("div");
  text.className = "badge-text";
  const title = document.createElement("b");
  title.textContent = "???";
  const what = document.createElement("span");
  what.className = "dim small";
  what.textContent = "A secret badge. Keep playing to find it";
  text.append(title, what);
  li.append(m, text);
  return li;
}

const levelName = (level) => BADGE_LEVEL_TITLES[level - 1] || "";

// ---------------------------------------------------------------------------
// Your Stats tab: every badge, its level and the way to the next one
// ---------------------------------------------------------------------------
function renderBadges(stats, into) {
  const head = document.createElement("h3");
  const got = BADGES.filter((b) => badgeLevel(stats, b) > 0).length;
  head.textContent = `Badges · ${got} of ${BADGES.length}`;
  const grid = document.createElement("ul");
  grid.className = "badge-grid";
  for (const b of BADGES) {
    const lvl = badgeLevel(stats, b);
    const have = badgeValue(stats, b.stat);
    if (b.secret && !lvl) { grid.append(secretCard()); continue; }
    const li = document.createElement("li");
    li.className = "badge-card" + (lvl ? "" : " locked");
    const text = document.createElement("div");
    text.className = "badge-text";
    const title = document.createElement("b");
    title.textContent = b.title;
    const lv = document.createElement("span");
    lv.className = "badge-lvl";
    lv.textContent = lvl ? `${levelName(lvl)}${lvl === b.levels.length ? " · max" : ""}` : "Not yet";
    const top = document.createElement("div");
    top.className = "badge-top";
    top.append(title, lv);
    const goal = document.createElement("span");
    goal.className = "dim small";
    const bar = document.createElement("div");
    bar.className = "badge-bar";
    const fill = document.createElement("i");
    if (lvl < b.levels.length) {
      const need = b.levels[lvl], from = lvl ? b.levels[lvl - 1] : 0;
      goal.textContent = `${badgeGoal(b, need)} · ${Math.floor(Math.min(have, need))}/${need}`;
      fill.style.width = `${Math.max(0, Math.min(1, (have - from) / (need - from))) * 100}%`;
    } else {
      goal.textContent = badgeGoal(b, b.levels[lvl - 1]);
      fill.style.width = "100%";
    }
    bar.append(fill);
    text.append(top, goal, bar);
    li.title = b.levels.map((n, k) => `${levelName(k + 1)}: ${badgeGoal(b, n)}`).join("\n");
    li.append(badgeMedal(b, lvl), text);
    grid.append(li);
  }
  into.append(head, grid);
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
