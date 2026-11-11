// bonk web client: Ratings (the server's rating.py): rank badges, the
// leaderboard page (/leaderboard), your rating on your Stats tab and how a
// match changed it on the results screen.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// The tiers, lowest first (the server picks one for each rating)
const TIERS = {
  bronze: { title: "Bronze", gem: "◆" },
  silver: { title: "Silver", gem: "◆" },
  gold: { title: "Gold", gem: "◆" },
  platinum: { title: "Platinum", gem: "◆" },
  diamond: { title: "Diamond", gem: "♦" },
  champion: { title: "Champion", gem: "♛" },
};

// A rank badge: the tier's gem and colour, and the rating. While someone's
// still placing (their first few matches), it says so instead of a tier
function rankBadge(r, opts = {}) {
  const t = TIERS[r.tier] || TIERS.silver;
  const b = document.createElement("span");
  b.className = `rank-badge tier-${r.tier}` + (r.placing ? " placing" : "") + (opts.big ? " big" : "");
  const gem = document.createElement("span");
  gem.className = "gem";
  gem.setAttribute("aria-hidden", "true");
  gem.textContent = t.gem;
  const text = document.createElement("span");
  text.textContent = opts.title === false ? String(r.rating) : `${t.title} ${r.rating}`;
  b.append(gem, text);
  b.title = r.placing
    ? `${t.title}, rating ${r.rating}. ${r.placing} more match${r.placing === 1 ? "" : "es"} to get on the leaderboard`
    : `${t.title}, rating ${r.rating}`;
  return b;
}

const signedChange = (n) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : "±0");

// ---------------------------------------------------------------------------
// The leaderboard page
// ---------------------------------------------------------------------------
async function fetchBoard() {
  const r = await fetch("/api/leaderboard", { credentials: "same-origin" });
  if (!r.ok) throw new Error("leaderboard " + r.status);
  return r.json();
}

function openLeaderboard(push) {
  if (push) history.pushState({}, "", "/leaderboard");
  show("leaderboard");
  renderBoard(null);
  fetchBoard().then(renderBoard, () => {
    $("board-summary").textContent = "Couldn't load the leaderboard. Try again in a moment.";
  });
}

function boardBall(ball) {
  const hex = ball.own_color || (PALETTE[ball.color] || PALETTE[0])[1];
  return ballCanvas(28, hex, ball.pattern || "plain", ball.hat || "none");
}

function renderBoard(d) {
  const list = $("board-list");
  list.innerHTML = "";
  $("board-empty").classList.add("hidden");
  if (!d) { $("board-summary").textContent = "Loading…"; return; }
  for (const el of document.querySelectorAll(".board-placement")) el.textContent = d.placement;
  $("board-summary").textContent = !d.accounts
    ? "Sign-in is off on this server, so there's no leaderboard."
    : `${plural(d.total, "player")} ranked`;
  for (const p of d.players) {
    const li = document.createElement("li");
    li.className = "board-row" + (p.you ? " you" : "") + (p.rank <= 3 ? ` top top-${p.rank}` : "");
    li.setAttribute("role", "row");
    const rank = document.createElement("span");
    rank.className = "board-rank";
    rank.textContent = p.rank;
    const who = document.createElement("span");
    who.className = "board-who";
    const name = document.createElement("b");
    name.textContent = p.name + (p.you ? " (you)" : "");
    who.append(boardBall(p.ball), name);
    const cells = [rank, who, rankBadge(p), rtNum(p.rating, "rating"), rtNum(p.games), rtNum(`${Math.round((100 * p.wins) / Math.max(1, p.games))}%`)];
    for (const c of cells) {
      const cell = document.createElement("span");
      cell.setAttribute("role", "cell");
      cell.className = c.className && c.className.startsWith("num") ? "num" : "";
      cell.append(c);
      li.append(cell);
    }
    list.append(li);
  }
  if (!d.players.length && d.accounts) {
    $("board-empty").textContent = `Nobody's on it yet. Sign in and play ${d.placement} matches against other signed-in players to be the first.`;
    $("board-empty").classList.remove("hidden");
  }
}

function rtNum(v, cls) {
  const s = document.createElement("span");
  s.className = "num" + (cls ? " " + cls : "");
  s.textContent = v;
  return s;
}

function rtText(tag, cls, t) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  e.textContent = t;
  return e;
}

function youLine(r) {
  if (r.placing) return `${r.placing} more match${r.placing === 1 ? "" : "es"} against signed-in players to get on the leaderboard.`;
  return `You're #${r.rank}. Best ever: ${r.peak}. ${r.wins} win${r.wins === 1 ? "" : "s"} in ${r.games} rated match${r.games === 1 ? "" : "es"}.`;
}

$("open-leaderboard").addEventListener("click", () => openLeaderboard(true));
$("board-back").addEventListener("click", () => { history.pushState({}, "", "/"); show("home"); });

// ---------------------------------------------------------------------------
// Your rating on your Stats tab (stats.js calls this)
// ---------------------------------------------------------------------------
function renderMyRating() {
  const box = $("stats-rating");
  box.innerHTML = "";
  box.classList.remove("rated");
  if (!profileStore.user) {
    box.append(rtText("p", "dim small", "Sign in to get a rating and a place on the leaderboard."));
    return;
  }
  fetchBoard().then((d) => {
    box.innerHTML = "";
    if (!d.you) return;
    const r = d.you;
    // A card: your place, your tier and rating, your best
    const place = rtText("span", `rating-place tier-${r.tier}`, r.placing ? "–" : `#${r.rank}`);
    const text = document.createElement("div");
    text.className = "rating-text";
    text.append(rtText("b", "", `${(TIERS[r.tier] || TIERS.silver).title} · ${r.rating}`),
      rtText("span", "dim small", r.placing ? youLine(r)
        : `#${r.rank} of ${d.total} on the leaderboard · best ${r.peak}`));
    const link = document.createElement("button");
    link.className = "link-button";
    link.textContent = "Leaderboard";
    link.addEventListener("click", () => { closeMe(); openLeaderboard(true); });
    box.append(place, text, link);
    box.classList.add("rated");
  }, () => {});
}

// ---------------------------------------------------------------------------
// The results screen: what the match did to your rating (results.js)
// ---------------------------------------------------------------------------
function renderRatingChange(msg, slots) {
  const p = $("rating-change");
  const ratings = msg.ratings || {};
  const mine = slots.findIndex((s) => s.id === me.id);
  const r = mine >= 0 ? ratings[String(mine)] : null;
  p.classList.toggle("hidden", !r);
  p.innerHTML = "";
  if (!r) return;
  const ch = rtText("b", "change " + (r.change > 0 ? "up" : r.change < 0 ? "down" : ""), signedChange(r.change));
  p.append(rtText("span", "", "Rating "), ch, rtText("span", "", " "), rankBadge(r));
}

// Next to a name in the standings: their change
function ratingChip(msg, slot) {
  const r = (msg.ratings || {})[String(slot)];
  if (!r) return null;
  const s = rtText("span", "rating-chip " + (r.change > 0 ? "up" : r.change < 0 ? "down" : ""), signedChange(r.change));
  s.title = `Rating ${r.before} → ${r.rating}`;
  return s;
}
