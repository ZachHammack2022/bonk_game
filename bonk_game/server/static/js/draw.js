// bonk web client: Drawing the match: the level, balls, power-ups and HUD, at 60 fps.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------
const canvas = $("canvas");
const ctx = canvas.getContext("2d");
let view = { scale: 1 };

function resize() {
  const vw = window.innerWidth, vh = window.innerHeight;
  const scale = Math.min(vw / W, vh / H);
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${W * scale}px`;
  canvas.style.height = `${H * scale}px`;
  canvas.width = Math.round(W * scale * dpr);
  canvas.height = Math.round(H * scale * dpr);
  view = { scale: scale * dpr };
}
window.addEventListener("resize", resize);

function roundRect(x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function circle(x, y, r, color) {
  ctx.beginPath();
  ctx.arc(x, y, Math.max(0.5, r), 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
}
function poly(points, color) {
  ctx.beginPath();
  points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}
function line(a, b, color, width) {
  ctx.beginPath();
  ctx.moveTo(a[0], a[1]);
  ctx.lineTo(b[0], b[1]);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.stroke();
}

function drawBackground() {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, T.bgTop);
  g.addColorStop(1, T.bgBottom);
  ctx.fillStyle = g;
  ctx.fillRect(-50, -50, W + 100, H + 100);
  const r = ctx.createRadialGradient(W / 2, H * 0.3, 0, W / 2, H * 0.3, W * 0.5);
  r.addColorStop(0, "rgba(255,255,255,0.11)");
  r.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = r;
  ctx.fillRect(0, 0, W, H);
}

function drawEdges() {
  const t = 18, c = "rgba(239,83,80,0.24)", z = "rgba(239,83,80,0)";
  let g = ctx.createLinearGradient(0, 0, t, 0);
  g.addColorStop(0, c); g.addColorStop(1, z);
  ctx.fillStyle = g; ctx.fillRect(0, 0, t, H);
  g = ctx.createLinearGradient(W, 0, W - t, 0);
  g.addColorStop(0, c); g.addColorStop(1, z);
  ctx.fillStyle = g; ctx.fillRect(W - t, 0, t, H);
  g = ctx.createLinearGradient(0, H, 0, H - t);
  g.addColorStop(0, c); g.addColorStop(1, z);
  ctx.fillStyle = g; ctx.fillRect(0, H - t, W, t);
}

function drawRect(s) {
  const [x1, y1, x2, y2] = s.r;
  const x = Math.min(x1, x2), y = Math.min(y1, y2), w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
  const rad = Math.min(5, h / 2, w / 2), lip = Math.min(3, h / 3);
  ctx.fillStyle = "rgba(0,0,0,0.235)";
  roundRect(x, y + 4, w, h, rad); ctx.fill();
  ctx.fillStyle = darken(s.c, 0.28);
  roundRect(x, y, w, h, rad); ctx.fill();
  ctx.fillStyle = s.c;
  roundRect(x, y, w, h - lip, rad); ctx.fill();

  ctx.save();
  roundRect(x, y, w, h, rad); ctx.clip();
  if (s.k === "hazard") {
    ctx.fillStyle = darken(s.c, 0.18);
    for (let sx = x - h; sx < x + w + h; sx += 24) poly([[sx, y + h], [sx + 12, y + h], [sx + 12 + h, y], [sx + h, y]], ctx.fillStyle);
  } else if (s.k === "pad") {
    const size = Math.max(2, Math.min(h / 2, 5)), cy = y + h / 2;
    ctx.strokeStyle = darken(s.c, 0.25);
    ctx.lineWidth = 2;
    for (let cx = x + size * 2; cx < x + w - size; cx += size * 4) {
      ctx.beginPath();
      ctx.moveTo(cx - size, cy + size / 2); ctx.lineTo(cx, cy - size / 2); ctx.lineTo(cx + size, cy + size / 2);
      ctx.stroke();
    }
  }
  ctx.restore();
  if (w > 2 * rad + 2 && h > 4) line([x + rad, y + 1], [x + w - rad - 1, y + 1], lighten(s.c, 0.4), 1.5);
}

// A slab's face: its corners, with the bottom two moved up by the lip
// (same as oriented_face in bonk_game/server/scene.py)
function polyFace(p, lip) {
  const toward = (a, b) => {
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    return [a[0] + (b[0] - a[0]) * lip / d, a[1] + (b[1] - a[1]) * lip / d];
  };
  return [p[0], p[1], toward(p[2], p[1]), toward(p[3], p[0])];
}

function drawPoly(shape) {
  const s = { ...shape, f: polyFace(shape.p, shape.l) };
  poly(s.p.map(([x, y]) => [x, y + 4]), "rgba(0,0,0,0.235)");
  poly(s.p, darken(s.c, 0.28));
  poly(s.f, s.c);
  if (s.k === "hazard") {
    ctx.beginPath(); s.f.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath();
    ctx.strokeStyle = darken(s.c, 0.18); ctx.lineWidth = 2; ctx.stroke();
  } else if (s.k === "pad") {
    const mid = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t)];
    const l = mid(s.f[0], s.f[3], 0.5), r = mid(s.f[1], s.f[2], 0.5);
    line(mid(l, r, 0.2), mid(l, r, 0.8), darken(s.c, 0.25), 2);
  }
  line(s.f[0], s.f[1], lighten(s.c, 0.4), 1.5);
}

function drawBumper(s) {
  circle(s.x, s.y + 4, s.r, "rgba(0,0,0,0.235)");
  circle(s.x, s.y, s.r, darken(s.c, 0.28));
  circle(s.x, s.y - 1.5, s.r - 1.5, s.c);
  if (s.k === "pad") {
    circle(s.x, s.y - 1.5, s.r * 0.62, darken(s.c, 0.22));
    circle(s.x, s.y - 1.5, s.r * 0.42, s.c);
  } else if (s.k === "hazard") {
    circle(s.x, s.y - 1.5, s.r * 0.5, darken(s.c, 0.2));
  }
  circle(s.x - s.r * 0.35, s.y - s.r * 0.4, Math.max(1, s.r * 0.2), lighten(s.c, 0.5));
}

function drawRail(s) {
  line([s.x1, s.y], [s.x2, s.y], darken(T.rail, 0.3), 5);
  line([s.x1, s.y], [s.x2, s.y], T.rail, 3);
  for (const x of [s.x1, s.x2]) { circle(x, s.y, 5, T.rail); circle(x, s.y, 2, darken(T.rail, 0.4)); }
}

function drawShape(s) {
  switch (s.t) {
    case "edges": return drawEdges();
    case "rect": return drawRect(s);
    case "poly": return drawPoly(s);
    case "ball": return drawBumper(s);
    case "line": return line(s.a, s.b, s.c, s.w);
    case "pivot": circle(s.x, s.y, 6, darken(T.rope, 0.3)); return circle(s.x, s.y, 3, lighten(T.rope, 0.3));
    case "rail": return drawRail(s);
  }
}

function drawWalls(walls, t) {
  if (!walls) return;
  const [left, right] = walls;
  const pulse = 0.5 + 0.5 * Math.sin(t * 8);
  ctx.fillStyle = `rgba(239,83,80,${(70 + 30 * pulse) / 255})`;
  if (left > -40) ctx.fillRect(-40, -40, left + 40, H + 80);
  if (right < W + 40) ctx.fillRect(right, -40, W + 40 - right, H + 80);
  for (const x of [left, right]) line([x, -40], [x, H + 40], lighten(T.danger, 0.25 + 0.25 * pulse), 3);
}

function drawPlayer(x, y, r, heavy, color, pattern, hat) {
  drawBall(ctx, x, y, r, heavy, color, pattern, true, hat);
}

// A ball on any canvas context `g`: rim, fill, pattern, shine (and a hat: looks.js)
function drawBall(g, x, y, r, heavy, color, pattern = "plain", shadow = true, hat = "none") {
  const dot = (cx, cy, rr, c) => { g.beginPath(); g.arc(cx, cy, Math.max(0.5, rr), 0, Math.PI * 2); g.fillStyle = c; g.fill(); };
  if (shadow) dot(x, y + 4, r, "rgba(0,0,0,0.215)");
  else r -= 1;
  const rim = darken(color, 0.5);
  const fill = mix(color, darken(color, 0.3), heavy);
  const rimW = Math.max(1.5, r * 0.18) + heavy * r * 0.35;
  dot(x, y, r, rim);
  const ri = r - rimW;
  dot(x, y, ri, fill);
  if (pattern && pattern !== "plain") {
    g.save();
    g.beginPath(); g.arc(x, y, ri, 0, Math.PI * 2); g.clip();
    drawPattern(g, x, y, ri, pattern, fill);
    g.restore();
  }
  if (pattern !== "eyes" && pattern !== "smile") dot(x - r * 0.32, y - r * 0.34, Math.max(1, r * 0.22), lighten(fill, 0.55));
  if (hat && hat !== "none") drawHat(g, x, y, r, hat);
}

function drawPattern(g, x, y, r, pattern, fill) {
  const ink = darken(fill, 0.28);
  const dot = (cx, cy, rr, c) => { g.beginPath(); g.arc(cx, cy, Math.max(0.5, rr), 0, Math.PI * 2); g.fillStyle = c; g.fill(); };
  g.fillStyle = ink; g.strokeStyle = ink;
  switch (pattern) {
    case "stripes":
      g.lineWidth = r * 0.32;
      for (let k = -3; k <= 3; k++) {
        const o = k * r * 0.75;
        g.beginPath(); g.moveTo(x - r + o, y + r); g.lineTo(x + r + o, y - r); g.stroke();
      }
      break;
    case "dots":
      dot(x, y, r * 0.2, ink);
      for (let k = 0; k < 6; k++) {
        const a = k * Math.PI / 3 + Math.PI / 6;
        dot(x + Math.cos(a) * r * 0.62, y + Math.sin(a) * r * 0.62, r * 0.16, ink);
      }
      break;
    case "ring":
      g.lineWidth = r * 0.22;
      g.beginPath(); g.arc(x, y, r * 0.55, 0, Math.PI * 2); g.stroke();
      break;
    case "split":
      g.beginPath(); g.moveTo(x, y - r); g.lineTo(x + r, y - r); g.lineTo(x + r, y + r); g.lineTo(x, y + r); g.closePath(); g.fill();
      break;
    case "star": {
      g.beginPath();
      for (let k = 0; k < 10; k++) {
        const a = -Math.PI / 2 + k * Math.PI / 5, rr = k % 2 ? r * 0.3 : r * 0.72;
        const px = x + Math.cos(a) * rr, py = y + Math.sin(a) * rr + r * 0.06;
        if (k) g.lineTo(px, py); else g.moveTo(px, py);
      }
      g.closePath(); g.fill();
      break;
    }
    case "zigzag":
      g.lineWidth = r * 0.24; g.lineJoin = "round";
      g.beginPath();
      for (let k = 0; k <= 6; k++) {
        const px = x - r + k * r / 3, py = y + (k % 2 ? -r * 0.22 : r * 0.22);
        if (k) g.lineTo(px, py); else g.moveTo(px, py);
      }
      g.stroke();
      break;
    case "eyes":
      for (const s of [-1, 1]) {
        dot(x + s * r * 0.36, y - r * 0.12, r * 0.27, "#ffffff");
        dot(x + s * r * 0.36 + r * 0.07, y - r * 0.08, r * 0.13, "#1d2433");
      }
      break;
    case "swirl":
      g.lineWidth = r * 0.2; g.lineCap = "round";
      g.beginPath();
      for (let k = 0; k <= 24; k++) {
        const a = k / 24 * Math.PI * 3.2, rr = r * 0.78 * k / 24;
        if (k) g.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); else g.moveTo(x, y);
      }
      g.stroke();
      break;
    case "smile":
      for (const s of [-1, 1]) dot(x + s * r * 0.32, y - r * 0.22, r * 0.13, ink);
      g.lineWidth = r * 0.14; g.lineCap = "round";
      g.beginPath(); g.arc(x, y + r * 0.02, r * 0.45, 0.2 * Math.PI, 0.8 * Math.PI); g.stroke();
      break;
    // (More patterns: cosmetics.py)
    case "heart": {
      const s = r * 0.62, cy = y + r * 0.08;
      g.beginPath();
      g.moveTo(x, cy + s * 0.75);
      g.bezierCurveTo(x - s * 1.2, cy - s * 0.1, x - s * 0.55, cy - s * 0.95, x, cy - s * 0.38);
      g.bezierCurveTo(x + s * 0.55, cy - s * 0.95, x + s * 1.2, cy - s * 0.1, x, cy + s * 0.75);
      g.fillStyle = "#ffffff"; g.globalAlpha *= 0.85; g.fill(); g.globalAlpha /= 0.85;
      break;
    }
    case "checker": {
      const n = 4, c = (2 * r) / n;
      g.save();
      g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.clip();
      for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) if ((i + j) % 2) g.fillRect(x - r + i * c, y - r + j * c, c, c);
      g.restore();
      break;
    }
    case "galaxy": {
      // A swirl of little stars
      g.lineWidth = r * 0.14; g.lineCap = "round";
      for (const arm of [0, Math.PI]) {
        g.beginPath();
        for (let k = 0; k <= 12; k++) {
          const t = k / 12, a = arm + t * Math.PI * 1.3, rr = r * (0.12 + 0.68 * t);
          const px = x + Math.cos(a) * rr, py = y + Math.sin(a) * rr;
          if (k) g.lineTo(px, py); else g.moveTo(px, py);
        }
        g.stroke();
      }
      for (const [a, d, s] of [[0.6, 0.55, 0.09], [2.4, 0.7, 0.07], [3.9, 0.45, 0.08], [5.3, 0.72, 0.06], [1.5, 0.3, 0.06]]) {
        dot(x + Math.cos(a) * r * d, y + Math.sin(a) * r * d, r * s, "#ffffff");
      }
      break;
    }
    case "flame": {
      const flame = (s, c) => {
        g.beginPath();
        g.moveTo(x, y + r * 0.8 * s);
        g.bezierCurveTo(x - r * 0.75 * s, y + r * 0.6 * s, x - r * 0.5 * s, y - r * 0.2 * s, x - r * 0.1 * s, y - r * 0.85 * s);
        g.bezierCurveTo(x + r * 0.05 * s, y - r * 0.4 * s, x + r * 0.35 * s, y - r * 0.45 * s, x + r * 0.3 * s, y - r * 0.75 * s);
        g.bezierCurveTo(x + r * 0.8 * s, y - r * 0.2 * s, x + r * 0.7 * s, y + r * 0.6 * s, x, y + r * 0.8 * s);
        g.fillStyle = c; g.fill();
      };
      flame(1, "#ff6b00"); flame(0.6, "#ffd43b");
      break;
    }
    case "bolt":
      g.beginPath();
      [[0.15, -0.85], [-0.45, 0.1], [-0.02, 0.1], [-0.2, 0.85], [0.45, -0.18], [0.04, -0.18], [0.25, -0.85]]
        .forEach(([px, py], i) => (i ? g.lineTo(x + px * r, y + py * r) : g.moveTo(x + px * r, y + py * r)));
      g.closePath(); g.fillStyle = "#ffe066"; g.fill();
      g.lineWidth = Math.max(0.8, r * 0.06); g.strokeStyle = ink; g.stroke();
      break;
    case "target":
      g.lineWidth = r * 0.16;
      g.strokeStyle = "#ffffff";
      g.beginPath(); g.arc(x, y, r * 0.72, 0, Math.PI * 2); g.stroke();
      g.strokeStyle = ink;
      g.beginPath(); g.arc(x, y, r * 0.45, 0, Math.PI * 2); g.stroke();
      dot(x, y, r * 0.17, "#ffffff");
      break;
  }
}

function drawYouMarker(x, y, r, color) {
  const tx = x, ty = y - r - 9, s = 5;
  const pts = [[tx, ty + s], [tx - s, ty - s * 0.6], [tx + s, ty - s * 0.6]];
  poly(pts, "#ffffff");
  ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.closePath();
  ctx.strokeStyle = darken(color, 0.5); ctx.lineWidth = 1.2; ctx.stroke();
}

function drawOffscreen(x, y, r, color) {
  if (y + r >= 0) return;
  const tx = clamp(x, 14, W - 14), s = 9;
  poly([[tx, 4], [tx - s, 4 + s * 1.4], [tx + s, 4 + s * 1.4]], color);
}

function text(str, size, color, x, y, opts = {}) {
  ctx.font = `${opts.weight || 800} ${size}px ui-rounded, "Nunito", "Avenir Next", "Segoe UI", system-ui, sans-serif`;
  ctx.textAlign = opts.align || "center";
  ctx.textBaseline = "middle";
  ctx.globalAlpha = opts.alpha ?? 1;
  if (opts.shadow !== false) {
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillText(str, x, y + Math.max(1, size / 14));
  }
  ctx.fillStyle = color;
  ctx.fillText(str, x, y);
  ctx.globalAlpha = 1;
}

function pill(x, y, w, h, alpha = 0.78, border = null) {
  ctx.fillStyle = `rgba(19,27,43,${alpha})`;
  roundRect(x, y, w, h, h / 2); ctx.fill();
  if (border) { ctx.strokeStyle = border; ctx.lineWidth = 2; roundRect(x, y, w, h, h / 2); ctx.stroke(); }
}

// Blend the two states either side of the moment we draw (clock.js says
// which). If the next state is late, carry on along the way things were
// moving for up to BonkClock.GUESS_MS, rather than stopping.
let drawFrozen = false;   // this frame had nothing newer and was past guessing: everything stood still
let drawGuessed = false;  // this frame was extrapolated past the newest state
function blendedState(now) {
  const S = app.states;
  if (!S.length) return null;
  const at = replayer.active ? replayer.drawTick() : playClock.tick(now);
  const n = S.length;
  if (at === null || n === 1) return S[n - 1][1];
  let i = n - 1;
  while (i > 1 && S[i - 1][1].tick > at) i--;
  const a = S[i - 1][1], b = S[i][1];
  if (at <= a.tick) return a;  // (older than we kept: just after a new match or a seek)
  const span = Math.max(1, b.tick - a.tick);
  let t = (at - a.tick) / span;
  if (t > 1) {
    // Past the newest state: guess, but not for long, and not across a reset
    if (replayer.active) return b;
    t = Math.min(t, 1 + BonkClock.GUESS_MS / (TICK_MS * span));
    if (playClock.paused) drawFrozen = true; else drawGuessed = true;
  }
  const roundReset = (b.events || []).some((e) => e.e === "round");
  if (roundReset || a.players.length !== b.players.length) return b;
  const players = b.players.map((p, k) => {
    const q = a.players[k];
    if (!q[3] || !p[3] || Math.abs(p[0] - q[0]) > MAX_JUMP || Math.abs(p[1] - q[1]) > MAX_JUMP) return p;
    return [lerp(q[0], p[0], t), lerp(q[1], p[1], t), lerp(q[2], p[2], Math.min(t, 1)), p[3]];
  });
  const level = b.level.map((s, k) => blendShape(a.level[k], s, t));
  const out = { ...b, players, level };
  // The attack plane and its bombs (super.js), blended the same way
  if (a.plane && b.plane && a.plane[0] === b.plane[0]) out.plane = [b.plane[0], lerp(a.plane[1], b.plane[1], t), ...b.plane.slice(2)];
  if (a.copies && b.copies && a.copies.length === b.copies.length && a.copies.every((c, k) => c[0] === b.copies[k][0])) {
    out.copies = b.copies.map((c, k) => {
      const q = a.copies[k];
      if (Math.abs(c[1] - q[1]) > MAX_JUMP || Math.abs(c[2] - q[2]) > MAX_JUMP) return c;
      return [c[0], lerp(q[1], c[1], t), lerp(q[2], c[2], t), c[3]];
    });
  }
  if (a.bombs && b.bombs && a.bombs.length === b.bombs.length) out.bombs = b.bombs.map((p, k) => [lerp(a.bombs[k][0], p[0], t), lerp(a.bombs[k][1], p[1], t)]);
  return out;
}

function blendShape(a, b, t) {
  if (!a || a.t !== b.t) return b;
  const pt = (p, q) => (Math.abs(p[0] - q[0]) > MAX_JUMP || Math.abs(p[1] - q[1]) > MAX_JUMP ? q : [lerp(p[0], q[0], t), lerp(p[1], q[1], t)]);
  switch (b.t) {
    case "rect": {
      const [ax1, ay1] = pt([a.r[0], a.r[1]], [b.r[0], b.r[1]]);
      const dx = ax1 - b.r[0], dy = ay1 - b.r[1];
      return { ...b, r: [b.r[0] + dx, b.r[1] + dy, b.r[2] + dx, b.r[3] + dy] };
    }
    case "poly":
      if (a.p.length !== b.p.length) return b;
      return { ...b, p: b.p.map((q, k) => pt(a.p[k], q)) };
    case "ball": { const [x, y] = pt([a.x, a.y], [b.x, b.y]); return { ...b, x, y }; }
    case "line": return { ...b, a: pt(a.a, b.a), b: pt(a.b, b.b) };
    case "rail": return { ...b, x1: lerp(a.x1, b.x1, t), x2: lerp(a.x2, b.x2, t) };
    default: return b;
  }
}

// Teams: one chip per team with its members' balls
function drawTeamScores(st) {
  const M = app.match;
  const chipW = 190, gap = 10, x0 = W / 2 - chipW - gap / 2;
  const mine = M.slots.find((x) => x.id === me.id);
  [0, 1].forEach((t) => {
    const x = x0 + t * (chipW + gap);
    pill(x, 8, chipW, 30, 0.78, mine && mine.team === t ? T.accent : M.team_colors[t]);
    text(M.team_names[t], 12, M.team_colors[t], x + 14, 23, { align: "left", shadow: false });
    const members = M.slots.map((s, i) => [s, i]).filter(([s]) => s.team === t);
    members.forEach(([s, i], k) => circle(x + 92 + k * 13, 23, 5, st.players[i][3] ? s.color : darken(s.color, 0.55)));
    text(String(st.team_scores[t]), 16, T.text, x + chipW - 16, 23, { shadow: false });
  });
}

function drawCrown(x, y, r) {
  const w = r * 1.1, h = r * 0.6, base = y - r * 0.72;
  const pts = [[x - w / 2, base], [x - w / 2, base - h], [x - w / 4, base - h * 0.45], [x, base - h * 1.1],
    [x + w / 4, base - h * 0.45], [x + w / 2, base - h], [x + w / 2, base]];
  poly(pts, "#ffd166");
  ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.closePath();
  ctx.strokeStyle = "#a0803a"; ctx.lineWidth = 1.5; ctx.stroke();
  circle(x, base - h * 0.35, 2, "#ef5350");
}

function drawHud(st, now) {
  const M = app.match, n = st.players.length;
  if (st.team_scores) drawTeamScores(st);
  // Scoreboard: a chip per player
  else {
  const chipW = Math.min(n <= 4 ? 120 : 62, (W - 20) / n - 4);
  const x0 = W / 2 - (n * (chipW + 4) - 4) / 2;
  st.players.forEach((p, i) => {
    const slot = M.slots[i];
    const out = !p[3];
    const x = x0 + i * (chipW + 4);
    pill(x, 8, chipW, 30, out ? 0.45 : 0.78, slot.id === me.id ? T.accent : null);
    circle(x + 15, 23, 8, out ? darken(slot.color, 0.55) : slot.color);
    if (n <= 4) {
      const name = slot.id === me.id ? "You" : slot.name;
      ctx.save();
      ctx.beginPath(); ctx.rect(x + 27, 8, chipW - 58, 30); ctx.clip();
      text(name, 12, out ? T.faint : T.text, x + 28, 23, { align: "left", shadow: false });
      ctx.restore();
    }
    const score = M.mode === "lives" ? `♥${st.scores[i]}` : String(st.scores[i]);
    text(score, M.mode === "lives" ? 14 : 16, out ? T.faint : M.mode === "lives" ? "#ff8a8a" : T.text, x + chipW - (M.mode === "lives" ? 19 : 16), 23, { shadow: false });
    if (st.crown === i) drawCrown(x + 15, 23, 8);
  });
  }

  // Clock: the round timer, or the match clock in Knockouts
  const clock = (secs) => { const left = Math.ceil(secs); return [`${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`, left <= 10 ? T.accent : T.dim]; };
  let clockLabel = null;
  if (st.clock !== undefined) clockLabel = st.overtime ? ["OVERTIME", T.accent] : clock(st.clock);
  else if (st.timer !== null && st.timer !== undefined) clockLabel = st.walls ? ["SUDDEN DEATH", T.danger] : clock(st.timer);
  if (clockLabel) {
    const [label, color] = clockLabel;
    ctx.font = `800 13px system-ui`;
    const w = ctx.measureText(label).width + 28;
    pill(W / 2 - w / 2, H - 36, w, 24);
    text(label, 13, color, W / 2, H - 24, { shadow: false });
  }

  // Countdown
  if (st.phase === "countdown" && st.count) {
    const label = st.count_len === 3 ? String(st.count) : (st.count === 2 ? "Ready" : "Set");
    text(label, 64, T.text, W / 2, 150);
  }

  // Banner
  const b = fx.banner;
  if (b) {
    const age = (now - b.at) / 1000;
    if (age < 1.1) {
      const alpha = clamp((1.1 - age) * 4, 0, 1);
      const scale = 0.5 + 0.5 * easeOutBack(age * 4);
      ctx.save();
      const y = b.big ? 150 : 90;
      ctx.translate(W / 2, y);
      ctx.scale(scale, scale);
      text(b.text, b.big ? 46 : 34, b.color, 0, 0, { alpha });
      ctx.restore();
    }
  }

  const note = fx.note;
  if (note) {
    const age = (now - note.at) / 1000;
    if (age < 1.6) text(note.text, 18, note.color, W / 2, 124, { alpha: clamp((1.6 - age) * 3, 0, 1) });
  }

  drawFeed(now);

  if (net.rtt !== null && prefs.ping) {
    text(`${Math.round(net.rtt)} ms`, 10, T.faint, W - 8, H - 10, { align: "right", weight: 600, shadow: false });
  }

  if (st.phase === "countdown" && st.count_len === 3 && st.tick < 60) {
    text(`${M.mode_title}  ·  ${M.title}  ·  ${M.goal}`, 12, T.dim, W / 2, 56, { weight: 600, shadow: false });
  }
}

// Held after a respawn (`left` seconds to go): a ring that runs down, and
// for your own ball, the seconds left
function drawHold(x, y, R, left, slot) {
  const total = app.match.respawn_hold || 2;
  ctx.beginPath();
  ctx.arc(x, y, R + 5, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * clamp(left / total, 0, 1));
  ctx.strokeStyle = slot.color; ctx.lineWidth = 3; ctx.lineCap = "round"; ctx.stroke(); ctx.lineCap = "butt";
  if (slot.id === me.id) text(String(Math.ceil(left)), 14, T.text, x, y + 1, { weight: 800 });
}

let lastFrame = performance.now();
function frame(now) {
  requestAnimationFrame(frame);
  const ms = now - lastFrame;
  const dt = Math.min(0.1, ms / 1000);
  lastFrame = now;
  fx.update(dt);
  replayer.frame(now);
  if ($("game").classList.contains("hidden") || !app.match) return;
  drawFrozen = drawGuessed = false;
  let st = blendedState(now);
  playtest.frame(ms, drawFrozen, drawGuessed, replayer.active ? null : playClock.delay(now));
  ctx.setTransform(view.scale, 0, 0, view.scale, 0, 0);
  if (!st) { drawBackground(); text("Get ready…", 24, T.dim, W / 2, H / 2); return; }

  const sx = fx.shake ? (Math.random() - 0.5) * fx.shake : 0;
  const sy = fx.shake ? (Math.random() - 0.5) * fx.shake : 0;
  ctx.setTransform(view.scale, 0, 0, view.scale, sx * view.scale, sy * view.scale);
  drawBackground();
  for (const s of st.level) drawShape(s);
  drawWalls(st.walls, st.t);

  // Power-ups waiting to be picked up: a bobbing bubble with an icon
  for (const [x, y, k] of st.pickups || []) {
    const bob = Math.sin(now / 300 + x) * 2.5;
    const c = POWER_COLORS[k] || T.accent;
    if (k === "plane") {
      // The super one: spinning rays behind it
      ctx.save();
      ctx.translate(x, y + bob); ctx.rotate(now / 700);
      ctx.globalAlpha = 0.35;
      for (let r = 0; r < 8; r++) { ctx.rotate(Math.PI / 4); poly([[0, 0], [-4, 26], [4, 26]], r % 2 ? c : T.accent); }
      ctx.restore();
    }
    ctx.globalAlpha = 0.25 + 0.1 * Math.sin(now / 200);
    circle(x, y + bob, 16, c);
    ctx.globalAlpha = 1;
    circle(x, y + bob, 11, "rgba(19,27,43,0.85)");
    ctx.beginPath(); ctx.arc(x, y + bob, 11, 0, Math.PI * 2); ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.stroke();
    text(POWER_ICONS[k] || "?", 12, T.text, x, y + bob + 1, { shadow: false });
  }

  for (const r of fx.rings) {
    const k = r.age / r.life;
    ctx.beginPath(); ctx.arc(r.x, r.y, 20 + 30 * k, 0, Math.PI * 2);
    ctx.strokeStyle = r.color; ctx.globalAlpha = 1 - k; ctx.lineWidth = 3; ctx.stroke(); ctx.globalAlpha = 1;
  }
  for (const p of fx.parts) drawPart(p);
  ctx.globalAlpha = 1;
  drawBooms(now);

  const R = app.match.radius;
  const showNames = st.players.length > 2;
  const mine = app.match.slots.findIndex((s) => s.id === me.id);
  const ownAt = ownPosition(now, dt);
  if (ownAt && mine >= 0) {
    // A copy: st may be a stored server state, which prediction still reads
    const players = st.players.slice();
    players[mine] = [ownAt[0], ownAt[1], st.players[mine][2], 1];
    st = { ...st, players };
  }
  // (The pilot is up in the plane: their ball's out of play)
  const flying = st.plane ? st.plane[0] : null;
  drawTrails(st.players.map((p, i) => (i === flying ? [p[0], p[1], p[2], 0] : p)), app.match.slots, R, now);
  // A giant's bigger (st.sizes, while anyone's a different size)
  const size = (i) => (st.sizes ? st.sizes[i] : R);
  drawCopies(st, R);
  st.players.forEach((p, i) => {
    if (!p[3] || i === flying) return;
    const slot = app.match.slots[i];
    const Ri = size(i);
    const eff = st.effects && st.effects[i];
    if (eff) {
      // A glow in the power-up's colour, fading as it runs out
      const c = POWER_COLORS[eff[0]] || T.accent;
      ctx.globalAlpha = clamp(eff[1] / 1.5, 0.25, 1) * (0.45 + 0.15 * Math.sin(now / 120));
      circle(p[0], p[1], Ri + 6, c);
      ctx.globalAlpha = 1;
    }
    if (st.hole && st.hole.i === i) { drawHoleBall(st.hole, p[0], p[1], Ri, slot, p[2], now); return; }
    const held = st.held && st.held[i];
    if (held) ctx.globalAlpha = 0.5 + 0.15 * Math.sin(now / 90);  // see-through, flickering
    else if (eff && eff[0] === "ghost") ctx.globalAlpha = 0.38 + 0.08 * Math.sin(now / 150);  // see-through
    drawPlayer(p[0], p[1], Ri, p[2], slot.color, slot.pattern, slot.hat);
    ctx.globalAlpha = 1;
    if (held) drawHold(p[0], p[1], Ri, held, slot);
  });
  if (mine >= 0) debug.drawn = { x: st.players[mine][0], y: st.players[mine][1], t: now };
  drawSuper(st, now);
  st.players.forEach((p, i) => {
    if (!p[3] || i === flying) return;
    const slot = app.match.slots[i];
    // (Above the hat, if there is one)
    const Ri = size(i);
    const up = slot.hat && slot.hat !== "none" ? Ri * 0.8 : 0;
    if (st.crown === i) drawCrown(p[0], p[1] - up, Ri);
    if (slot.id === me.id) drawYouMarker(p[0], p[1] - up - (st.crown === i ? 8 : 0), Ri, slot.color);
    else if (showNames && slot.kind === "human") text(slot.name.slice(0, 10), 10, "rgba(241,245,249,0.75)", p[0], p[1] - up - Ri - 9, { weight: 700 });
    drawOffscreen(p[0], p[1], Ri, slot.color);
  });
  // Emote bubbles over balls
  fx.emotes = fx.emotes.filter((e) => now - e.at < 2000);
  for (const e of fx.emotes) {
    const p = st.players[e.slot];
    if (!p || !p[3]) continue;
    const age = (now - e.at) / 1000;
    const pop = easeOutBack(age * 5);
    const x = clamp(p[0], 20, W - 20), y = Math.max(22, p[1] - R - 30);
    ctx.globalAlpha = clamp((2 - age) * 3, 0, 1);
    ctx.fillStyle = "rgba(241,245,249,0.95)";
    roundRect(x - 17 * pop, y - 15 * pop, 34 * pop, 30 * pop, 12 * pop); ctx.fill();
    ctx.globalAlpha = 1;
    text(EMOTES[e.id] || "?", 18 * pop, T.text, x, y + 1, { shadow: false, alpha: clamp((2 - age) * 3, 0, 1) });
  }

  ctx.setTransform(view.scale, 0, 0, view.scale, 0, 0);
  drawHud(st, now);
  drawPilotHelp(st);
  drawSuperScene(st, now);
}
requestAnimationFrame(frame);
