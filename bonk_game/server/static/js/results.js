// bonk web client: The results screen: winner, standings and your awards.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// quiet: just redraw it (someone was muted), without the confetti
function showResults(msg, quiet) {
  const slots = msg.slots || (app.match && app.match.slots) || [];
  applyLooks({ mode: msg.mode, slots });  // (as the match looked on your screen)
  const w = msg.winner;
  const el = $("winner");
  const M = app.match || {};
  const teamWin = msg.winner_team;
  if (msg.team_scores) {
    const mine = slots.find((x) => x.id === me.id);
    if (teamWin === null || teamWin === undefined) { el.textContent = "Draw!"; el.style.color = T.text; }
    else {
      el.textContent = mine && mine.team === teamWin ? "Your team wins!" : `${M.team_names[teamWin]} wins!`;
      el.style.color = M.team_colors[teamWin];
    }
  } else if (w === null || w === undefined) {
    el.textContent = "Draw!";
    el.style.color = T.text;
  } else {
    const s = slots[w];
    el.textContent = s && s.id === me.id ? "You win!" : `${s ? s.name : "?"} wins!`;
    el.style.color = s ? s.color : T.text;
  }
  const ol = $("standings");
  ol.innerHTML = "";
  const order = msg.scores.map((sc, i) => i).sort((a, b) => msg.scores[b] - msg.scores[a]);
  const unit = { lives: (v) => `♥${v}`, crown: (v) => `${v} s` }[msg.mode] || String;
  if (msg.team_scores) {
    for (const t of [0, 1].sort((a, b) => msg.team_scores[b] - msg.team_scores[a])) {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = M.team_names[t] + ": " + slots.filter((s) => s.team === t).map((s) => s.id === me.id ? "You" : s.name).join(", ");
      name.style.color = M.team_colors[t];
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = msg.team_scores[t];
      li.append(name, score);
      ol.appendChild(li);
    }
  }
  for (const i of msg.team_scores ? [] : order) {
    const s = slots[i] || { name: "?", color: T.faint };
    const li = document.createElement("li");
    const ball = document.createElement("span");
    ball.className = "ball";
    Object.assign(ball.style, { width: "16px", height: "16px", borderRadius: "50%", background: s.color, flex: "none" });
    const name = document.createElement("span");
    name.textContent = s.id === me.id ? `${s.name} (you)` : s.name;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = unit(msg.scores[i]);
    li.append(ball, name);
    const chip = ratingChip(msg, i);  // (rating.js)
    if (chip) li.append(chip);
    li.append(score);
    if (s.kind === "human" && s.id && s.id !== me.id ) li.append(personButton(s.id, s.base ? s.base.name : s.name));
    ol.appendChild(li);
  }
  renderAwards(msg, slots);
  renderRatingChange(msg, slots);
  renderEarned(app.earned);  // (badges.js: what this match earned you)
  $("results").classList.remove("hidden");
  $("emotes").classList.add("hidden");
  const quick = !!(app.lobby && app.lobby.quick);
  $("next-help").classList.toggle("hidden", quick);
  $("next-quick").classList.toggle("hidden", !quick);
  if (quiet) return;
  if (w !== null && w !== undefined) fx.confetti(slots[w] ? slots[w].color : T.accent);
  else if (teamWin !== null && teamWin !== undefined && M.team_colors) fx.confetti(M.team_colors[teamWin]);
}

const AWARD_ICONS = { kos: "💥", hit: "🔨", falls: "🧈", survivor: "🛡️", pickups: "🍬" };
const POWER_ICONS = { speed: "⚡", float: "🎈", iron: "🪨", punch: "👊", swap: "🔀", ghost: "👻",
  plane: "✈️", hole: "🕳️", giant: "🐘", swarm: "🐝" };
const POWER_COLORS = { speed: "#ffd166", float: "#9be7ff", iron: "#a0aec6", punch: "#ff8a65", swap: "#7ed6aa",
  ghost: "#dfe6f0", plane: "#ff5ca8", hole: "#a66bff", giant: "#ff9f43", swarm: "#ffe066" };
// What each one does (the lobby's tooltips)
const POWER_HINTS = {
  speed: "Push harder and go faster",
  float: "Low gravity: jump higher, fall slower",
  iron: "As heavy as a heavy ball, without slowing down",
  punch: "The next ball you bump goes flying",
  swap: "Trade places with a random opponent, at once",
  ghost: "Pass through other balls for 5 s",
  plane: "Super (rare): fly an attack plane for 10 s and drop 2 bombs",
  hole: "Super (rare): you become a black hole for 6 s: everyone's pulled in, and touching you knocks them out",
  giant: "Super (rare): twice the size and much heavier for 8 s",
  swarm: "Super (rare): 3 copies of you for 10 s; only the real you can be knocked out",
};

function awardDetail(a) {
  switch (a.id) {
    case "kos": return `${a.value} knockout${a.value === 1 ? "" : "s"}`;
    case "hit": return `power ${Math.round(a.value)}`;
    case "falls": return `fell ${a.value} time${a.value === 1 ? "" : "s"}`;
    case "survivor": return a.value ? `out ${a.value === 1 ? "once" : a.value + " times"}` : "never out";
    case "pickups": return `${a.value} power-up${a.value === 1 ? "" : "s"}`;
  }
  return "";
}

// Just the awards you won (not everyone else's)
function renderAwards(msg, slots) {
  const ul = $("awards");
  ul.innerHTML = "";
  const mine = (a) => a.slots.some((i) => slots[i] && slots[i].id === me.id);
  for (const a of (msg.awards || []).filter(mine)) {
    const li = document.createElement("li");
    li.dataset.award = a.id;
    const icon = document.createElement("span");
    icon.className = "icon";
    icon.textContent = AWARD_ICONS[a.id] || "🏅";
    const body = document.createElement("span");
    body.className = "body";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = a.title;
    const who = document.createElement("span");
    who.className = "who";
    for (const [k, i] of a.slots.entries()) {
      const s = slots[i] || { name: "?", color: T.faint };
      if (k) who.append(" & ");
      const name = document.createElement("b");
      name.style.color = s.color;
      name.textContent = s.id === me.id ? "You" : s.name;
      who.append(name);
    }
    who.append(" · " + awardDetail(a));
    body.append(title, who);
    li.append(icon, body);
    ul.appendChild(li);
  }
  ul.classList.toggle("hidden", !ul.children.length);
}
