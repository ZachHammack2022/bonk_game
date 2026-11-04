// bonk web client: How balls look. Hats, trails and knockout effects
// (cosmetics: bonk_game/server/cosmetics.py), and how
// the balls are coloured on your screen (your own colour, colourblind mode).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Hats: on top of a ball of radius r at (x, y), on any canvas context g
// ---------------------------------------------------------------------------
function drawHat(g, x, y, r, hat) {
  const shape = (pts, fill) => {
    g.beginPath(); pts.forEach(([px, py], i) => (i ? g.lineTo(px, py) : g.moveTo(px, py))); g.closePath();
    g.fillStyle = fill; g.fill();
  };
  const top = y - r;
  g.save();
  switch (hat) {
    case "cap":
      g.beginPath(); g.arc(x - r * 0.05, top + r * 0.42, r * 0.62, Math.PI, 0); g.closePath();
      g.fillStyle = "#3b5bdb"; g.fill();
      shape([[x + r * 0.2, top + r * 0.3], [x + r * 1.05, top + r * 0.36], [x + r * 1.0, top + r * 0.5], [x + r * 0.2, top + r * 0.46]], "#2b3f9e");
      g.beginPath(); g.arc(x - r * 0.05, top - r * 0.2, r * 0.1, 0, Math.PI * 2); g.fillStyle = "#2b3f9e"; g.fill();
      break;
    case "party": {
      const bx = x + r * 0.05, by = top + r * 0.3, tipX = x + r * 0.2, tipY = top - r * 0.85;
      shape([[bx - r * 0.42, by], [bx + r * 0.42, by], [tipX, tipY]], "#f06595");
      g.save();
      g.beginPath(); g.moveTo(bx - r * 0.42, by); g.lineTo(bx + r * 0.42, by); g.lineTo(tipX, tipY); g.closePath(); g.clip();
      g.strokeStyle = "#ffd43b"; g.lineWidth = r * 0.13;
      for (let k = 0; k < 4; k++) {
        const yy = by - k * r * 0.32;
        g.beginPath(); g.moveTo(bx - r, yy + r * 0.12); g.lineTo(bx + r, yy - r * 0.12); g.stroke();
      }
      g.restore();
      g.beginPath(); g.arc(tipX, tipY, r * 0.14, 0, Math.PI * 2); g.fillStyle = "#ffffff"; g.fill();
      break;
    }
    case "tophat":
      g.fillStyle = "#1d2433";
      g.fillRect(x - r * 0.72, top + r * 0.18, r * 1.44, r * 0.2);
      g.fillRect(x - r * 0.46, top - r * 0.72, r * 0.92, r * 0.94);
      g.fillStyle = "#e03131";
      g.fillRect(x - r * 0.46, top - r * 0.02, r * 0.92, r * 0.18);
      break;
    case "halo":
      g.beginPath(); g.ellipse(x, top - r * 0.32, r * 0.62, r * 0.2, 0, 0, Math.PI * 2);
      g.strokeStyle = "#ffe066"; g.lineWidth = Math.max(1.5, r * 0.16); g.shadowColor = "#ffe066"; g.shadowBlur = r * 0.5;
      g.stroke();
      break;
    case "horns":
      for (const s of [-1, 1]) {
        g.beginPath();
        g.moveTo(x + s * r * 0.2, top + r * 0.32);
        g.quadraticCurveTo(x + s * r * 0.55, top - r * 0.1, x + s * r * 0.62, top - r * 0.62);
        g.quadraticCurveTo(x + s * r * 0.7, top + r * 0.05, x + s * r * 0.62, top + r * 0.42);
        g.closePath(); g.fillStyle = "#f1f3f5"; g.fill();
        g.strokeStyle = "#868e96"; g.lineWidth = Math.max(0.8, r * 0.06); g.stroke();
      }
      break;
  }
  g.restore();
}

// ---------------------------------------------------------------------------
// Trails: where a ball has been lately (pts: [{x, y, t}], oldest first)
// ---------------------------------------------------------------------------
const TRAIL_MS = 200;

function drawTrail(g, pts, trail, color, r, now) {
  const n = pts.length;
  if (n < 2) return;
  g.save();
  g.lineCap = "round";
  for (let k = 1; k < n; k++) {
    const a = pts[k - 1], b = pts[k];
    const f = k / n;  // 0 oldest .. 1 newest
    switch (trail) {
      case "comet":
        g.globalAlpha = 0.55 * f;
        g.strokeStyle = color; g.lineWidth = r * 1.7 * f;
        g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
        break;
      case "rainbow":
        g.globalAlpha = 0.7 * f;
        g.strokeStyle = `hsl(${(k * 28 + now / 4) % 360}, 90%, 65%)`; g.lineWidth = r * 0.9;
        g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
        break;
      case "sparkle":
        if (k % 2) break;
        g.globalAlpha = f;
        sparkle(g, b.x + Math.sin(k * 2.3) * r * 0.5, b.y + Math.cos(k * 1.7) * r * 0.5, r * 0.3 * (0.6 + 0.4 * Math.sin(now / 60 + k)), "#ffffff");
        break;
      case "bubbles":
        if (k % 3) break;
        g.globalAlpha = 0.8 * f;
        g.strokeStyle = lighten(color, 0.4); g.lineWidth = Math.max(1, r * 0.09);
        g.beginPath(); g.arc(b.x + Math.sin(k * 1.9) * r * 0.4, b.y + Math.cos(k * 1.3) * r * 0.4, r * (0.18 + 0.12 * ((k * 7) % 3)), 0, Math.PI * 2); g.stroke();
        break;
    }
  }
  g.restore();
}

// A four-pointed twinkle
function sparkle(g, x, y, s, color) {
  g.beginPath();
  for (let k = 0; k < 8; k++) {
    const a = k * Math.PI / 4, rr = k % 2 ? s * 0.3 : s;
    if (k) g.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); else g.moveTo(x + rr, y);
  }
  g.closePath(); g.fillStyle = color; g.fill();
}

// Each ball's recent path, kept as the match is drawn (fx.trails[slot])
function drawTrails(players, slots, r, now) {
  players.forEach((p, i) => {
    const trail = slots[i] && slots[i].trail;
    if (!trail || trail === "none") return;
    const pts = fx.trails[i] || (fx.trails[i] = []);
    const last = pts[pts.length - 1];
    // Not there, or jumped (respawned, a replay skipped): start again
    if (!p[3] || (last && (Math.hypot(p[0] - last.x, p[1] - last.y) > MAX_JUMP || now < last.t))) pts.length = 0;
    if (!p[3]) return;
    if (!last || now - last.t > 12) pts.push({ x: p[0], y: p[1], t: now });
    while (pts.length && now - pts[0].t > TRAIL_MS) pts.shift();
    drawTrail(ctx, pts.concat([{ x: p[0], y: p[1], t: now }]), trail, slots[i].color, r, now);
  });
}

// ---------------------------------------------------------------------------
// Knockout effects: what a knocked-out ball turns into
// ---------------------------------------------------------------------------
function knockoutEffect(x, y, color, ko) {
  switch (ko) {
    case "confetti":
      for (const c of [color, "#ffd43b", "#4dabf7", "#f06595", "#40c057"]) fx.burst(x, y, c, 10, 9, 4, 1.1, true, "square");
      break;
    case "stars":
      fx.burst(x, y, "#ffe066", 14, 8, 7, 0.9, false, "star");
      fx.burst(x, y, color, 16, 6, 4);
      break;
    case "ghost":
      fx.parts.push({ x, y, vx: 0, vy: -1.4, color, size: 13, life: 1.3, age: 0, gravity: false, shape: "ghost" });
      fx.burst(x, y, color, 14, 5, 3.5, 0.5);
      break;
    case "fireworks":
      fx.ring(x, y, color, 0.6);
      [[0, -40, color], [-34, -18, "#ffd43b"], [34, -22, "#4dabf7"]].forEach(([dx, dy, c]) => {
        fx.burst(x + dx, y + dy, c, 18, 6, 3.5, 0.9, false);
        fx.burst(x + dx, y + dy, "#ffffff", 6, 3, 2.5, 0.6, false);
      });
      break;
    default:  // pop
      fx.burst(x, y, color, 34, 9);
      fx.burst(x, y, T.text, 10, 5, 3);
  }
}

// One particle (fx.parts), on ctx
function drawPart(p) {
  const k = p.age / p.life;
  ctx.globalAlpha = clamp(1 - k, 0, 1);
  const s = p.size * (1 - 0.5 * k);
  switch (p.shape) {
    case "star": sparkle(ctx, p.x, p.y, s * 1.3, p.color); break;
    case "square":
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.age * 9 + p.size);
      ctx.fillStyle = p.color; ctx.fillRect(-s, -s * 0.6, s * 2, s * 1.2); ctx.restore();
      break;
    case "ghost": {
      // A little ghost of the ball floating up, swaying
      const gx = p.x + Math.sin(p.age * 6) * 4, gy = p.y, r = p.size;
      ctx.globalAlpha *= 0.75;
      ctx.beginPath();
      ctx.arc(gx, gy, r, Math.PI, 0);
      for (let w = 0; w <= 4; w++) ctx.lineTo(gx + r - w * r / 2, gy + r * (w % 2 ? 0.7 : 1));
      ctx.closePath(); ctx.fillStyle = lighten(p.color, 0.55); ctx.fill();
      ctx.globalAlpha /= 0.75;
      circle(gx - r * 0.35, gy - r * 0.1, r * 0.17, "#1d2433");
      circle(gx + r * 0.35, gy - r * 0.1, r * 0.17, "#1d2433");
      break;
    }
    default: circle(p.x, p.y, s, p.color);
  }
}

// ---------------------------------------------------------------------------
// Pickers: a little picture of each pattern, trail, hat or knockout effect
// ---------------------------------------------------------------------------
function lookCanvas(size, kind, id, color, pattern) {
  if (kind === "pattern") return ballCanvas(size, color, id);
  if (kind === "hat") return ballCanvas(size, color, pattern, id);
  const c = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  c.width = c.height = Math.round(size * dpr);
  c.style.width = c.style.height = size + "px";
  c.className = "ball-canvas";
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  const r = size * 0.24;
  if (kind === "trail") {
    // Coming in from the bottom left
    const pts = [];
    for (let k = 0; k <= 14; k++) pts.push({ x: size * (0.1 + 0.55 * k / 14), y: size * (0.85 - 0.45 * k / 14 - 0.1 * Math.sin(k / 4)), t: 0 });
    drawTrail(g, pts, id, color, r, 500);
    drawBall(g, pts[14].x, pts[14].y, r, 0, color, pattern, false);
  } else {
    // Knockout: the burst it makes
    const m = size / 2;
    const ring = (n, rr, fn) => { for (let k = 0; k < n; k++) { const a = k * 2 * Math.PI / n + 0.3; fn(m + Math.cos(a) * rr, m + Math.sin(a) * rr, k); } };
    const dot = (x, y, rr, col) => { g.beginPath(); g.arc(x, y, rr, 0, Math.PI * 2); g.fillStyle = col; g.fill(); };
    if (id === "pop") { ring(8, size * 0.3, (x, y) => dot(x, y, size * 0.07, color)); ring(5, size * 0.14, (x, y) => dot(x, y, size * 0.04, T.text)); }
    if (id === "confetti") ring(9, size * 0.3, (x, y, k) => { g.fillStyle = [color, "#ffd43b", "#4dabf7", "#f06595", "#40c057"][k % 5]; g.fillRect(x - 3, y - 2, 6, 4); });
    if (id === "stars") ring(6, size * 0.28, (x, y) => sparkle(g, x, y, size * 0.12, "#ffe066"));
    if (id === "ghost") {
      g.beginPath(); g.arc(m, m - 2, size * 0.28, Math.PI, 0);
      for (let w = 0; w <= 4; w++) g.lineTo(m + size * 0.28 - w * size * 0.14, m - 2 + size * (w % 2 ? 0.2 : 0.28));
      g.closePath(); g.fillStyle = lighten(color, 0.55); g.fill();
      dot(m - size * 0.1, m - 4, size * 0.05, "#1d2433"); dot(m + size * 0.1, m - 4, size * 0.05, "#1d2433");
    }
    if (id === "fireworks") {
      for (const [cx, cy, col] of [[m, m - 5, color], [m - 8, m + 6, "#ffd43b"], [m + 8, m + 5, "#4dabf7"]]) {
        for (let k = 0; k < 6; k++) { const a = k * Math.PI / 3; dot(cx + Math.cos(a) * 5, cy + Math.sin(a) * 5, 1.5, col); }
      }
    }
  }
  return c;
}

// A row of buttons, one per pattern (or trail, hat, knockout effect). Locked
// ones are shown with a 🔒 and say how to unlock them.
function lookRow(kind, current, color, pattern, onPick) {
  const row = document.createElement("div");
  row.className = "patterns looks-" + kind;
  const items = looks.catalog ? looks.catalog[kind]
    : kind === "pattern" ? PATTERNS.map((id) => ({ id, name: PATTERN_NAMES[id], unlocked: true }))
    : [{ id: looks.DEFAULT[kind], name: "None", unlocked: true }];
  for (const it of items) {
    const b = document.createElement("button");
    b.className = "pattern" + (it.id === current ? " on" : "");
    b.title = it.name;
    b.setAttribute("aria-label", `${looks.LABELS[kind]}: ${it.name}`);
    b.dataset[kind === "pattern" ? "pattern" : "look"] = it.id;
    b.appendChild(lookCanvas(30, kind, it.id, color, pattern));
    if (!it.unlocked) {
      b.classList.add("locked");
      b.title = `${it.name}: ${looks.how(it)}`;
      b.addEventListener("click", () => toast(`${it.name}: ${looks.how(it)}`));
    } else b.addEventListener("click", () => onPick(it.id));
    row.appendChild(b);
  }
  return row;
}

// ---------------------------------------------------------------------------
// How the balls are coloured on your screen
// - Your ball is always your colour (your own, or your favourite), even if
//   someone else has it here; anyone close to it looks different instead.
//   (In Teams colours show the sides, so they stay.)
// - Colourblind mode: a different pattern on every ball, so you never have
//   to tell colours apart. High contrast: colours that are easy to tell apart.
// ---------------------------------------------------------------------------
const MIN_COLOR_GAP = 70;  // as on the server (lobby.py)
// Okabe & Ito's colourblind-safe colours, and a few more
const CONTRAST = ["#e69f00", "#56b4e9", "#f0e442", "#cc79a7", "#d55e00", "#009e73", "#ffffff", "#0072b2", "#999999", "#7f3b08"];
const CONTRAST_NAMES = ["Orange", "Sky", "Yellow", "Pink", "Vermilion", "Green", "White", "Blue", "Grey", "Brown"];
const CONTRAST_TEAMS = [["#e69f00", "#d55e00", "#f0e442", "#ffc966", "#a65e00"], ["#56b4e9", "#0072b2", "#a8d8f5", "#2b6cb0", "#7fb8e0"]];
const CONTRAST_TEAM_HEX = ["#e69f00", "#56b4e9"];
const COLORBLIND_PATTERNS = ["stripes", "dots", "ring", "split", "star", "zigzag", "checker", "target", "bolt", "smile"];
const colorGap = (a, b) => Math.hypot(...rgb(a).map((c, i) => c - rgb(b)[i]));

function applyLooks(M) {
  if (!M || !M.slots) return;
  for (const s of M.slots) if (!s.base) s.base = { color: s.color, pattern: s.pattern || "plain", name: s.name, color_name: s.color_name };
  if (!M.base_team_colors) M.base_team_colors = M.team_colors;
  const teams = M.mode === "teams";
  const perTeam = [0, 0];
  const colors = M.slots.map((s, i) => {
    if (!prefs.contrast) return s.base.color;
    if (teams) { const t = s.team || 0; return CONTRAST_TEAMS[t][perTeam[t]++ % CONTRAST_TEAMS[t].length]; }
    return CONTRAST[i % CONTRAST.length];
  });
  const mine = M.slots.findIndex((s) => s.id === me.id);
  const want = me.ownColor || (me.color !== null ? PALETTE[me.color][1] : null);
  if (mine >= 0 && want && !teams && !prefs.contrast) {
    colors[mine] = want;
    const spare = PALETTE.map((p) => p[1]).concat(CONTRAST);
    colors.forEach((c, i) => {
      if (i === mine || colorGap(c, want) >= MIN_COLOR_GAP) return;
      const free = spare.find((f) => colors.every((o, j) => j === i || colorGap(f, o) >= MIN_COLOR_GAP));
      if (free) colors[i] = free;
    });
  }
  let patterns = M.slots.map((s) => s.base.pattern);
  if (prefs.colorblind) {
    // Everyone keeps a pattern of their own; plain balls and repeats get one
    const used = new Set();
    patterns = patterns.map((p) => (p !== "plain" && !used.has(p) ? (used.add(p), p) : null));
    patterns = patterns.map((p) => {
      if (p) return p;
      const q = COLORBLIND_PATTERNS.find((x) => !used.has(x)) || PATTERNS.find((x) => x !== "plain" && !used.has(x)) || "stripes";
      used.add(q);
      return q;
    });
  }
  // Bots are named by colour ("Blue bot"): a bot that looks different here
  // goes by the colour you see
  const nameOf = (hex) => {
    const p = PALETTE.find((x) => x[1] === hex);
    if (p) return p[0];
    const k = CONTRAST.indexOf(hex);
    return k >= 0 ? CONTRAST_NAMES[k] : null;
  };
  M.slots.forEach((s, i) => {
    s.color = colors[i]; s.pattern = patterns[i];
    s.name = s.base.name; s.color_name = s.base.color_name;
    const now = colors[i] !== s.base.color && nameOf(colors[i]);
    if (now && s.base.color_name) {
      s.color_name = now;
      if (s.kind !== "human" && s.base.name.startsWith(s.base.color_name + " ")) s.name = now + s.base.name.slice(s.base.color_name.length);
    }
    if (isMuted(s.id)) s.name = MUTED_NAME;  // (people.js)
  });
  if (M.base_team_colors) M.team_colors = prefs.contrast ? CONTRAST_TEAM_HEX.slice() : M.base_team_colors;
}
