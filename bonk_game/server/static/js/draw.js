// bonk web client: Drawing the match: the level, balls, power-ups and HUD, at 60 fps.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------
const canvas = $("canvas");
// (let: the scenery cache below draws into its own canvas through it for a moment)
let ctx = canvas.getContext("2d");
let view = { scale: 1 };

// The notch and home bar (non-zero only from the home screen, style.css)
function safeInsets() {
  const css = getComputedStyle(document.documentElement);
  const px = (k) => parseFloat(css.getPropertyValue(k)) || 0;
  return { x: px("--safe-l") + px("--safe-r"), y: px("--safe-t") + px("--safe-b") };
}
function resize() {
  const safe = safeInsets();
  const vw = window.innerWidth - safe.x, vh = window.innerHeight - safe.y;
  const scale = Math.min(vw / W, vh / H);
  // At most 2 pixels per CSS pixel: 3x phones would draw 2.25 times as many
  // pixels every frame for a difference you can't see
  const dpr = Math.min(2, window.devicePixelRatio || 1);
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

// The sky: a pastel gradient, drifting clouds and soft hills far below
const CLOUDS = [[90, 70, 1], [330, 40, 0.8], [600, 95, 1.15], [820, 55, 0.9]];
function drawSky() {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, T.bgTop);
  g.addColorStop(1, T.bgBottom);
  ctx.fillStyle = g;
  ctx.fillRect(-50, -50, W + 100, H + 100);
  ctx.fillStyle = "rgba(160,215,170,0.45)";
  for (let k = -1; k < 9; k++) { ctx.beginPath(); ctx.arc(k * 120 + 40, H + 70, 110, 0, Math.PI * 2); ctx.fill(); }
}
function drawClouds() {
  const t = performance.now() / 1000;
  ctx.fillStyle = "rgba(255,255,255,0.8)";
  for (const [cx, cy, s] of CLOUDS) {
    const x = ((cx + t * 6 * s + 120) % (W + 240)) - 120;
    for (const [dx, dy, r] of [[0, 0, 20], [22, -10, 26], [48, 0, 19], [24, 7, 21]]) {
      ctx.beginPath(); ctx.arc(x + dx * s, cy + dy * s, r * s, 0, Math.PI * 2); ctx.fill();
    }
  }
}
function drawBackground() { drawSky(); drawClouds(); }

// The scenery that doesn't move (the sky, and every piece of the level that
// hasn't moved since the match began) is drawn once into two canvases and
// copied each frame; only the clouds and moving pieces are drawn fresh.
// A piece that moves is drawn fresh from then on. Redrawn when the window
// changes size or a new match starts.
const scenery = { match: null, first: null, moving: new Set(), w: 0, h: 0, sky: null, ground: null, dirty: true };
function drawScenery(st) {
  const level = st.level;
  if (scenery.match !== app.match || !scenery.first || scenery.first.length !== level.length) {
    Object.assign(scenery, { match: app.match, first: level.map((sh) => JSON.stringify(sh)), moving: new Set(), dirty: true });
  }
  level.forEach((sh, k) => {
    if (!scenery.moving.has(k) && JSON.stringify(sh) !== scenery.first[k]) { scenery.moving.add(k); scenery.dirty = true; }
  });
  if (scenery.w !== canvas.width || scenery.h !== canvas.height) scenery.dirty = true;
  if (scenery.dirty) buildScenery(level);
  // (A shake shows past the edges: draw the sky itself then, wider than the screen)
  if (fx.shake) drawSky(); else ctx.drawImage(scenery.sky, 0, 0, W, H);
  drawClouds();
  ctx.drawImage(scenery.ground, 0, 0, W, H);
  level.forEach((sh, k) => { if (scenery.moving.has(k)) drawShape(sh); });
}
function buildScenery(level) {
  const layer = (old) => {
    const c = old || document.createElement("canvas");
    c.width = canvas.width; c.height = canvas.height;  // (also clears it)
    const g = c.getContext("2d");
    g.setTransform(view.scale, 0, 0, view.scale, 0, 0);
    return c;
  };
  scenery.sky = layer(scenery.sky);
  scenery.ground = layer(scenery.ground);
  const main = ctx;
  try {
    ctx = scenery.sky.getContext("2d");
    drawSky();
    ctx = scenery.ground.getContext("2d");
    level.forEach((sh, k) => { if (!scenery.moving.has(k)) drawShape(sh); });
  } finally {
    ctx = main;
  }
  scenery.w = canvas.width; scenery.h = canvas.height; scenery.dirty = false;
}

function drawEdges() {
  const t = 22, c = "rgba(255,110,140,0.22)", z = "rgba(255,110,140,0)";
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

// What a piece of the level is made of, for the critter look: grass on
// earth (platforms), stone (posts), wood, a springy pad, or a hazard
const MATERIALS = {
  grass: { body: "#e0b089", deep: "#c4916a", top: "#8fd694", shine: "#bdf0bd" },
  stone: { body: "#cfc7e3", deep: "#ada3c8", top: "#e6e0f3", shine: "#f6f3fb" },
  wood: { body: "#f0c08a", deep: "#d09a5e", top: "#f7d3a6", shine: "#fbe6c8" },
  pad: { body: "#b9ec6e", deep: "#8fcf45", top: "#d6f7a0", shine: "#effcd6" },
  hazard: { body: "#ff8a8a", deep: "#e65c6c", top: "#ffb0b0", shine: "#ffd6d6" },
};
const POST_HEX = "#68789c";
function materialOf(s) {
  if (s.k === "hazard") return MATERIALS.hazard;
  if (s.k === "pad") return MATERIALS.pad;
  if (s.k === "wood") return MATERIALS.wood;
  if (String(s.c).toLowerCase() === POST_HEX) return MATERIALS.stone;
  return MATERIALS.grass;
}
const SHADOW = "rgba(90,60,130,0.14)";

function drawRect(s) {
  const [x1, y1, x2, y2] = s.r;
  const x = Math.min(x1, x2), y = Math.min(y1, y2), w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
  const m = materialOf(s);
  const rad = Math.min(14, h / 2, w / 2);
  ctx.fillStyle = SHADOW;
  roundRect(x + 4, y + 7, w, h, rad); ctx.fill();
  ctx.fillStyle = m.deep;
  roundRect(x, y, w, h, rad); ctx.fill();
  ctx.fillStyle = m.body;
  roundRect(x, y, w, h - Math.min(4, h / 4), rad); ctx.fill();
  ctx.save();
  roundRect(x, y, w, h, rad); ctx.clip();
  const cap = Math.min(12, Math.max(4, h * 0.45));
  if (s.k === "hazard") {
    ctx.fillStyle = "rgba(255,255,255,0.45)";
    for (let sx = x - h; sx < x + w + h; sx += 22) poly([[sx, y + h], [sx + 10, y + h], [sx + 10 + h, y], [sx + h, y]], ctx.fillStyle);
  } else if (s.k === "pad") {
    const size = Math.max(2, Math.min(h / 2, 5)), cy = y + h / 2;
    ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2.5; ctx.lineCap = "round";
    for (let cx = x + size * 2; cx < x + w - size; cx += size * 4) {
      ctx.beginPath(); ctx.moveTo(cx - size, cy + size / 2); ctx.lineTo(cx, cy - size / 2); ctx.lineTo(cx + size, cy + size / 2); ctx.stroke();
    }
  } else if (m === MATERIALS.wood) {
    ctx.strokeStyle = m.deep; ctx.lineWidth = 1.5;
    for (let px = x + 36; px < x + w - 8; px += 44) { ctx.beginPath(); ctx.moveTo(px, y + 3); ctx.lineTo(px, y + h - 3); ctx.stroke(); }
  } else {
    ctx.fillStyle = m.top;
    roundRect(x, y - 2, w, cap + 2, Math.min(rad, cap / 2 + 1)); ctx.fill();
    if (h > cap + 6) {
      ctx.fillStyle = "rgba(255,255,255,0.3)";
      for (let px = x + 20; px < x + w - 10; px += 38) { ctx.beginPath(); ctx.arc(px + (px % 7), y + cap + (h - cap) * 0.55, 2.5, 0, Math.PI * 2); ctx.fill(); }
    }
  }
  ctx.restore();
  if (w > 2 * rad + 8 && h > 4) {
    ctx.fillStyle = m.shine;
    roundRect(x + Math.max(rad, 8), y + 1.5, w - 2 * Math.max(rad, 8), Math.min(4, h / 4), 2); ctx.fill();
  }
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
  const m = materialOf(shape);
  const p = shape.p, f = polyFace(p, shape.l);
  poly(p.map(([x, y]) => [x + 4, y + 7]), SHADOW);
  poly(p, m.deep);
  poly(f, m.body);
  // The top edge (p0 -> p1) gets the grass or frosting, as thick as fits
  const side = Math.hypot(p[3][0] - p[0][0], p[3][1] - p[0][1]) || 1;
  const cap = Math.min(10, side * 0.45);
  const n = [(p[3][0] - p[0][0]) / side * cap, (p[3][1] - p[0][1]) / side * cap];
  if (shape.k === "hazard") {
    ctx.beginPath(); f.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath();
    ctx.strokeStyle = "rgba(255,255,255,0.6)"; ctx.lineWidth = 2; ctx.setLineDash([6, 6]); ctx.stroke(); ctx.setLineDash([]);
  } else if (m !== MATERIALS.wood) {
    poly([p[0], p[1], [p[1][0] + n[0], p[1][1] + n[1]], [p[0][0] + n[0], p[0][1] + n[1]]], m.top);
  }
  line(p[0], p[1], m.shine, 2);
}

function drawBumper(s) {
  const m = materialOf(s);
  circle(s.x + 3, s.y + 6, s.r, SHADOW);
  circle(s.x, s.y, s.r, m.deep);
  circle(s.x, s.y - 1.5, s.r - 2, m === MATERIALS.grass ? MATERIALS.stone.body : m.body);
  if (s.k === "pad") {
    circle(s.x, s.y - 1.5, s.r * 0.62, m.deep);
    circle(s.x, s.y - 1.5, s.r * 0.42, m.top);
  } else if (s.k === "hazard") {
    circle(s.x, s.y - 1.5, s.r * 0.5, "rgba(255,255,255,0.55)");
  }
  ctx.fillStyle = "rgba(255,255,255,0.6)";
  ctx.beginPath(); ctx.ellipse(s.x - s.r * 0.35, s.y - s.r * 0.45, s.r * 0.26, s.r * 0.15, -0.5, 0, Math.PI * 2); ctx.fill();
}

function drawRail(s) {
  line([s.x1, s.y], [s.x2, s.y], darken(T.rail, 0.25), 6);
  line([s.x1, s.y], [s.x2, s.y], T.rail, 3.5);
  for (const x of [s.x1, s.x2]) { circle(x, s.y, 6, "#ffffff"); circle(x, s.y, 3, darken(T.rail, 0.2)); }
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
  ctx.fillStyle = `rgba(255,110,140,${(60 + 30 * pulse) / 255})`;
  if (left > -40) ctx.fillRect(-40, -40, left + 40, H + 80);
  if (right < W + 40) ctx.fillRect(right, -40, W + 40 - right, H + 80);
  for (const x of [left, right]) line([x, -40], [x, H + 40], lighten(T.danger, 0.25 + 0.25 * pulse), 3);
}

function drawPlayer(x, y, r, heavy, color, pattern, hat, face = null) {
  drawBall(ctx, x, y, r, heavy, color, pattern, true, hat, face);
}

// A ball on any canvas context `g`: a critter with a face (critter.js), its
// pattern, and a hat (looks.js)
function drawBall(g, x, y, r, heavy, color, pattern = "plain", shadow = true, hat = "none", face = null) {
  drawCritter(g, x, y, r, heavy, color, pattern, shadow, hat, face);
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
  // A little bouncing arrow in your colour, outlined so it shows on the sky
  const tx = x, ty = y - r - 11 + Math.sin(performance.now() / 180) * 1.5, s = 6;
  const pts = [[tx, ty + s], [tx - s, ty - s * 0.6], [tx + s, ty - s * 0.6]];
  ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.closePath();
  ctx.lineJoin = "round"; ctx.strokeStyle = CRITTER_INK; ctx.lineWidth = 3.5; ctx.stroke();
  ctx.fillStyle = color; ctx.fill();
}

function drawOffscreen(x, y, r, color) {
  if (y + r >= 0) return;
  const tx = clamp(x, 14, W - 14), s = 9;
  poly([[tx, 4], [tx - s, 4 + s * 1.4], [tx + s, 4 + s * 1.4]], color);
}

function text(str, size, color, x, y, opts = {}) {
  ctx.font = `${Math.min(700, opts.weight || 700)} ${size}px ${T.font}`;
  ctx.textAlign = opts.align || "center";
  ctx.textBaseline = "middle";
  ctx.globalAlpha = opts.alpha ?? 1;
  if (opts.shadow !== false) {
    // An outline that stands out on the sky: dark round light text, white round dark
    ctx.lineJoin = "round";
    ctx.lineWidth = Math.max(3, size / 6);
    ctx.strokeStyle = isLight(color) ? "rgba(59,44,82,0.9)" : "rgba(255,255,255,0.92)";
    ctx.strokeText(str, x, y);
  }
  ctx.fillStyle = color;
  ctx.fillText(str, x, y);
  ctx.globalAlpha = 1;
}

// Is this colour (#rrggbb or rgb()/rgba()) light? (For text outlines)
function isLight(color) {
  const c = String(color);
  const v = c.startsWith("#") ? rgb(c) : (c.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(Number);
  return (0.299 * v[0] + 0.587 * v[1] + 0.114 * v[2]) / 255 > 0.6;
}

function pill(x, y, w, h, alpha = 0.78, border = null) {
  ctx.fillStyle = `rgba(90,60,130,${0.12 * alpha})`;
  roundRect(x, y + 3, w, h, h / 2); ctx.fill();
  ctx.fillStyle = `rgba(255,255,255,${Math.min(1, alpha + 0.15)})`;
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
    members.forEach(([s, i], k) => circle(x + 92 + k * 13, 23, 5, st.players[i][3] ? s.color : mix(s.color, "#e4dcef", 0.7)));
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

// The scoreboard changes only when a score, who's in, the crown or the
// window does: drawn into its own canvas then, and copied every frame
const board = { key: "", canvas: null };
function drawScoreboard(st) {
  const M = app.match;
  const key = JSON.stringify([canvas.width, canvas.height, M.mode, st.scores, st.team_scores, st.crown,
    st.players.map((p) => !!p[3]), M.slots.map((sl) => [sl.id === me.id, sl.name, sl.color, sl.team])]);
  if (key !== board.key || !board.canvas) {
    const c = board.canvas || document.createElement("canvas");
    c.width = canvas.width; c.height = Math.ceil(48 * view.scale);  // (the top 48 px of the game)
    const g = c.getContext("2d");
    g.setTransform(view.scale, 0, 0, view.scale, 0, 0);
    const main = ctx;
    try { ctx = g; if (st.team_scores) drawTeamScores(st); else drawChips(st); } finally { ctx = main; }
    board.canvas = c; board.key = key;
  }
  ctx.drawImage(board.canvas, 0, 0, W, board.canvas.height / view.scale);
}

// Scoreboard: a chip per player
function drawChips(st) {
  const M = app.match, n = st.players.length;
  const chipW = Math.min(n <= 4 ? 120 : 62, (W - 20) / n - 4);
  const x0 = W / 2 - (n * (chipW + 4) - 4) / 2;
  st.players.forEach((p, i) => {
    const slot = M.slots[i];
    const out = !p[3];
    const x = x0 + i * (chipW + 4);
    pill(x, 8, chipW, 30, out ? 0.45 : 0.78, slot.id === me.id ? T.accent : null);
    circle(x + 15, 23, 8, out ? mix(slot.color, "#e4dcef", 0.7) : slot.color);
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

function drawHud(st, now) {
  const M = app.match;
  drawScoreboard(st);

  // Clock: the round timer, or the match clock in Knockouts
  const clock = (secs) => { const left = Math.ceil(secs); return [`${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`, left <= 10 ? T.accent : T.dim]; };
  let clockLabel = null;
  if (st.clock !== undefined) clockLabel = st.overtime ? ["OVERTIME", T.accent] : clock(st.clock);
  else if (st.timer !== null && st.timer !== undefined) clockLabel = st.walls ? ["SUDDEN DEATH", T.danger] : clock(st.timer);
  if (clockLabel) {
    const [label, color] = clockLabel;
    ctx.font = `700 13px ${T.font}`;
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
  drawScenery(st);
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
    circle(x, y + bob, 11, "#ffffff");
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
    drawPlayer(p[0], p[1], Ri, p[2], slot.color, slot.pattern, slot.hat, critterFace(i, p[0], p[1], p[2], now));
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
    else if (showNames && slot.kind === "human") text(slot.name.slice(0, 10), 11, "#ffffff", p[0], p[1] - up - Ri - 10, { weight: 600 });
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
    ctx.fillStyle = "rgba(255,255,255,0.97)";
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
