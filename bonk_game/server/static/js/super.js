// bonk web client: The supers (server/powerups.py): their cutscenes; the
// attack plane, its bombs and their explosions; the black hole; a swarm's
// copies. The server runs them; this only draws what the state says.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

const PLANE_PINK = "#ff5ca8";
const BLAST_COLOR = "#ffb347";

// An attack plane facing `dir` (1 right, -1 left), its middle at x, y, with
// the pilot's ball in the cockpit. `prop`: the propeller's spin (radians).
function drawPlane(x, y, dir, s, slot, prop = 0, R = 20) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(dir * s, s);
  // Shadow
  ctx.fillStyle = "rgba(0,0,0,0.22)";
  ctx.beginPath(); ctx.ellipse(0, 9, 40, 9, 0, 0, Math.PI * 2); ctx.fill();
  // Back wing and tail fin
  poly([[-6, -2], [-22, -20], [-12, -20], [8, -2]], darken(PLANE_PINK, 0.25));
  poly([[-30, -4], [-42, -20], [-35, -20], [-22, -4]], PLANE_PINK);
  // Body
  const body = ctx.createLinearGradient(0, -12, 0, 12);
  body.addColorStop(0, "#f4f7fb"); body.addColorStop(1, "#aab6c8");
  ctx.fillStyle = body;
  ctx.beginPath();
  ctx.moveTo(34, -2);
  ctx.quadraticCurveTo(36, 10, 22, 11);
  ctx.lineTo(-30, 6);
  ctx.quadraticCurveTo(-40, 2, -36, -4);
  ctx.lineTo(-24, -9);
  ctx.quadraticCurveTo(16, -14, 34, -2);
  ctx.fill();
  ctx.strokeStyle = "rgba(19,27,43,0.45)"; ctx.lineWidth = 1.5; ctx.stroke();
  // A stripe and the nose
  poly([[-26, -1], [24, -3], [26, 2], [-26, 4]], PLANE_PINK);
  circle(34, 3, 4, "#ef5350");
  // Propeller (a blur, and one blade)
  ctx.globalAlpha = 0.35;
  ctx.fillStyle = "#e9eef6";
  ctx.beginPath(); ctx.ellipse(38, 3, 2.5, 13, 0, 0, Math.PI * 2); ctx.fill();
  ctx.globalAlpha = 1;
  const blade = Math.sin(prop) * 13;
  ctx.strokeStyle = "#3a4560"; ctx.lineWidth = 2.5;
  ctx.beginPath(); ctx.moveTo(38, 3 - blade); ctx.lineTo(38, 3 + blade); ctx.stroke();
  // Front wing
  poly([[-8, 3], [-20, 22], [-8, 22], [12, 3]], PLANE_PINK);
  ctx.restore();
  // The pilot, in the cockpit (drawn upright, whichever way the plane faces)
  if (slot) {
    const pr = R * 0.5 * s;
    drawBall(ctx, x + dir * 6 * s, y - 13 * s, pr, 0, slot.color, slot.pattern, false, "none");
    // The canopy
    ctx.save();
    ctx.translate(x + dir * 6 * s, y - 13 * s);
    ctx.globalAlpha = 0.28;
    circle(0, 0, pr + 3 * s, "#9be7ff");
    ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.arc(0, 0, pr + 3 * s, Math.PI, 2 * Math.PI);
    ctx.strokeStyle = "rgba(233,238,246,0.8)"; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.restore();
  }
}

function drawBomb(x, y, now) {
  ctx.save();
  ctx.translate(x, y);
  poly([[-4, -6], [4, -6], [6, -12], [-6, -12]], "#3a4560");  // tail fins
  circle(0, 0, 7, "#1d2433");
  circle(-2.2, -2.4, 2, "rgba(233,238,246,0.45)");
  ctx.restore();
  // A blinking light
  if (Math.floor(now / 120) % 2) circle(x, y + 1, 2, "#ef5350");
}

// The plane and its bombs, in the world (st.plane: [pilot, x, y, facing,
// seconds left, bombs left]; st.bombs: [[x, y]])
function drawSuper(st, now) {
  for (const [x, y] of st.bombs || []) drawBomb(x, y, now);
  const pl = st.plane;
  if (!pl) return;
  const [i, x, y, dir, left, bombs] = pl;
  const slot = app.match.slots[i];
  // A bit of bob, and a trail of exhaust behind
  const bob = Math.sin(now / 180) * 2;
  for (let k = 1; k <= 5; k++) {
    ctx.globalAlpha = 0.18 - k * 0.03;
    circle(x - dir * (40 + k * 11), y + 3 + bob + Math.sin(now / 90 + k) * 1.5, 6 + k * 1.5, "#e9eef6");
  }
  ctx.globalAlpha = 1;
  drawPlane(x, y + bob, dir, 1, slot, now / 25, app.match.radius);
  // Under the plane: bombs left, the time left as a bar, and who's flying
  for (let k = 0; k < bombs; k++) circle(x - 8 + k * 16, y + 28 + bob, 4.5, "#1d2433");
  const total = (app.match.powerups && app.match.powerups.plane && app.match.powerups.plane.seconds) || 10;
  pill(x - 26, y + 38 + bob, 52, 6, 0.6);
  ctx.fillStyle = PLANE_PINK;
  roundRect(x - 25, y + 39 + bob, 50 * clamp(left / total, 0, 1), 4, 2); ctx.fill();
  if (slot.id === me.id) text("YOU", 10, T.accent, x, y + 54 + bob, { weight: 800 });
  else text(slot.name.slice(0, 10), 10, "rgba(241,245,249,0.8)", x, y + 54 + bob, { weight: 700 });
}

// Your own plane: how to fly it, at the bottom of the screen
function drawPilotHelp(st) {
  const pl = st.plane;
  if (!pl || !isMe(pl[0])) return;
  const msg = pl[5] ? `← → to fly  ·  ↑ or heavy drops a bomb (${pl[5]} left)` : "Out of bombs!";
  ctx.font = "700 13px system-ui";
  const w = ctx.measureText(msg).width + 28;
  pill(W / 2 - w / 2, H - 66, w, 24, 0.78, PLANE_PINK);
  text(msg, 13, T.text, W / 2, H - 54, { weight: 700, shadow: false });
}

// The cutscene, while the match stands still (st.phase "super"): the
// screen dims, a band in the player's colour sweeps across with their name
// and the super's, and a little scene plays in it (the ball jumps into
// the plane, grows, splits into a swarm, or opens a black hole).
const superScene = { i: null, at: 0 };

function startSuperScene(i) {
  superScene.i = i;
  superScene.at = performance.now();
}

function drawSuperScene(st, now) {
  if (st.phase !== "super" || !st.super) { superScene.i = null; return; }
  const [i, kind] = st.super;
  // (Joined in the middle of one: start from here)
  if (superScene.i !== i) startSuperScene(i);
  const M = app.match, slot = M.slots[i];
  if (!slot) return;
  const info = (M.powerups && M.powerups[kind]) || {};
  const total = info.intro || 2.4;
  const t = (now - superScene.at) / 1000;
  const fadeIn = clamp(t / 0.2, 0, 1), fadeOut = clamp((total - t) / 0.25, 0, 1);
  const a = Math.min(fadeIn, fadeOut);

  ctx.save();
  // Dim everything
  ctx.globalAlpha = 0.6 * a;
  ctx.fillStyle = "#05070d";
  ctx.fillRect(0, 0, W, H);
  ctx.globalAlpha = a;

  // The band: a slanted strip that sweeps in from the left
  const cy = H / 2 + 10, half = 92, slant = 60;
  const sweep = (1 - easeOutBack(t / 0.35)) * -W;
  ctx.translate(sweep, 0);
  const band = ctx.createLinearGradient(0, cy - half, 0, cy + half);
  band.addColorStop(0, darken(slot.color, 0.45));
  band.addColorStop(0.5, slot.color);
  band.addColorStop(1, darken(slot.color, 0.55));
  ctx.fillStyle = band;
  ctx.beginPath();
  ctx.moveTo(-40, cy - half + slant / 2); ctx.lineTo(W + 40, cy - half - slant / 2);
  ctx.lineTo(W + 40, cy + half - slant / 2); ctx.lineTo(-40, cy + half + slant / 2);
  ctx.closePath(); ctx.fill();
  // Its edges, and speed lines rushing past
  ctx.save();
  ctx.clip();
  ctx.strokeStyle = "rgba(255,255,255,0.35)";
  for (let k = 0; k < 14; k++) {
    const yy = cy - half + ((k * 37) % (2 * half));
    const len = 60 + (k * 53) % 120;
    const xx = W - ((now * (0.9 + (k % 4) * 0.25) + k * 97) % (W + len + 80));
    ctx.lineWidth = 1 + (k % 3);
    ctx.beginPath(); ctx.moveTo(xx, yy - (xx / W - 0.5) * slant); ctx.lineTo(xx + len, yy - ((xx + len) / W - 0.5) * slant); ctx.stroke();
  }
  ctx.restore();
  ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 4;
  ctx.beginPath(); ctx.moveTo(-40, cy - half + slant / 2); ctx.lineTo(W + 40, cy - half - slant / 2); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(-40, cy + half + slant / 2); ctx.lineTo(W + 40, cy + half - slant / 2); ctx.stroke();

  const scene = { plane: planeScene, hole: holeScene, giant: giantScene, swarm: swarmScene }[kind] || planeScene;
  scene(t, total, a, cy, slot, M.radius, now);
  ctx.restore();

  // The words: who, and what
  const pop = easeOutBack((t - 0.15) / 0.35);
  if (pop > 0) {
    ctx.save();
    ctx.globalAlpha = a;
    ctx.translate(W * 0.3, cy - 18);
    ctx.rotate(-0.09);
    ctx.scale(pop, pop);
    text(slotName(i).toUpperCase(), 20, "#ffffff", 0, -38, { weight: 900, alpha: a });
    text(`${(info.title || kind).toUpperCase()}!`, 40, T.accent, 0, 0, { weight: 900, alpha: a });
    ctx.restore();
  }
  ctx.globalAlpha = 1;
}

// The ball runs in from the left (the first 0.45 s of each scene)
function runIn(t, x, y, r, slot) {
  const run = clamp(t / 0.45, 0, 1);
  drawBall(ctx, lerp(-40, x, easeOutBack(run)), y, r, 0, slot.color, slot.pattern, true, slot.hat);
}

// The plane waits on the right; the ball runs up and jumps in (0.45-1.15
// s), then it takes off up and away (from 1.4 s)
function planeScene(t, total, a, cy, slot, radius, now) {
  const s = 2.1;
  const px0 = W * 0.62, py0 = cy + 22;
  const go = clamp((t - 1.4) / (total - 1.55), 0, 1);
  const px = px0 + go * go * W * 0.9, py = py0 - go * go * 170;
  const R = radius * 1.6;
  const jump = clamp((t - 0.45) / 0.7, 0, 1);
  const inside = jump >= 1;
  if (go > 0) {
    for (let k = 1; k <= 7; k++) {
      ctx.globalAlpha = a * (0.3 - k * 0.035);
      circle(px - k * 26 * s * 0.5, py + 6 + k * 3, 10 + k * 3, "#ffffff");
    }
    ctx.globalAlpha = a;
  }
  ctx.save();
  ctx.translate(px, py); ctx.rotate(-go * 0.35); ctx.translate(-px, -py);
  drawPlane(px, py, 1, s, inside ? slot : null, now / 20, radius);
  ctx.restore();
  if (inside) return;
  const sx = W * 0.2, sy = cy + 40;
  if (jump <= 0) { runIn(t, sx, sy, R, slot); return; }
  // In a hop, to the cockpit
  const ex = px0 + 6 * s, ey = py0 - 13 * s;
  const bx = lerp(sx, ex, jump), by = lerp(sy, ey, jump) - Math.sin(Math.PI * jump) * 120;
  drawBall(ctx, bx, by, lerp(R, radius * 0.5 * s, jump), 0, slot.color, slot.pattern, true, slot.hat);
}

// The ball stops in the middle and grows (0.55-1.1 s), then stomps
function giantScene(t, total, a, cy, slot, radius) {
  const x = W * 0.66, ground = cy + 70;
  const R = radius * 1.6;
  const grow = easeOutBack((t - 0.55) / 0.55);
  const r = t < 0.55 ? R : lerp(R, R * 2.6, grow);
  const stomp = t > 1.3 ? Math.abs(Math.sin((t - 1.3) * 9)) * 26 * Math.max(0, 1 - (t - 1.3)) : 0;
  if (t > 1.3) fx.kick(4);
  // A shadow on the ground under it
  ctx.globalAlpha = a * 0.3;
  ctx.fillStyle = "#000";
  ctx.beginPath(); ctx.ellipse(x, ground, r * 0.9, 8, 0, 0, Math.PI * 2); ctx.fill();
  ctx.globalAlpha = a;
  if (t < 0.55) runIn(t, x, ground - R, R, slot);
  else drawBall(ctx, x, ground - r - stomp, r, 0, slot.color, slot.pattern, true, slot.hat);
}

// The ball runs to the middle and splits into a swarm (from 0.6 s): the
// copies fan out and they all hop together
function swarmScene(t, total, a, cy, slot, radius) {
  const x = W * 0.66, y = cy + 34;
  const R = radius * 1.4;
  if (t < 0.6) { runIn(t, x, y, R, slot); return; }
  const k = easeOutBack((t - 0.6) / 0.45);
  const hop = Math.abs(Math.sin((t - 0.6) * 7)) * 22;
  const spots = [-2.3, -1.15, 1.15, 0];  // (the real one last, in front)
  for (const d of spots) {
    if (d) ctx.globalAlpha = a * 0.9;
    drawBall(ctx, x + d * R * 1.9 * k, y - hop - (d ? 0 : 4), R, 0, slot.color, slot.pattern, true, d ? "none" : slot.hat);
    ctx.globalAlpha = a;
  }
}

// The ball throws something up and a black hole opens there (from 0.7 s),
// pulling streaks of light in
function holeScene(t, total, a, cy, slot, radius, now) {
  const bx = W * 0.5, by = cy + 46, hx = W * 0.74, hy = cy;
  const R = radius * 1.4;
  runIn(t, bx, by, R, slot);
  const open = easeOutBack((t - 0.7) / 0.5);
  if (open <= 0) return;
  drawHoleAt(hx, hy, 58 * open, now, a);
}

// --- the black hole ------------------------------------------------------------
// A black disc with a glowing ring, and streaks spiralling in
function drawHoleAt(x, y, r, now, alpha = 1) {
  ctx.save();
  const glow = ctx.createRadialGradient(x, y, r * 0.4, x, y, r * 2.2);
  glow.addColorStop(0, "rgba(160,90,255,0.55)");
  glow.addColorStop(0.5, "rgba(120,60,220,0.18)");
  glow.addColorStop(1, "rgba(120,60,220,0)");
  ctx.globalAlpha = alpha;
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(x, y, r * 2.2, 0, Math.PI * 2); ctx.fill();
  // Streaks, each on its own spiral, coming in
  ctx.strokeStyle = "rgba(220,200,255,0.7)";
  ctx.lineCap = "round";
  for (let k = 0; k < 10; k++) {
    const life = ((now / 900 + k / 10) % 1);
    const d = r * (2.4 - 1.5 * life);
    const ang = k * 2.4 + life * 3.2;
    ctx.globalAlpha = alpha * Math.sin(Math.PI * life) * 0.8;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, d, ang, ang + 0.5);
    ctx.stroke();
  }
  ctx.globalAlpha = alpha;
  ctx.lineWidth = Math.max(2, r * 0.12);
  ctx.strokeStyle = "#c79bff";
  ctx.beginPath(); ctx.arc(x, y, r * 0.75, now / 300, now / 300 + Math.PI * 1.6); ctx.stroke();
  circle(x, y, r * 0.62, "#000000");
  ctx.restore();
}

// st.hole: {i, x, y, t: seconds left, w: seconds before it pulls, near, ...}.
// While it's opening it grows, pulsing, inside a dashed ring that shows
// how far it reaches; then it pulls, and shrinks away at the end.
function drawHole(st, now) {
  const h = st.hole;
  if (!h) return;
  const k = (app.match.powerups && app.match.powerups.hole) || {};
  const core = k.core || 18, warning = k.warning || 1.2;
  const fade = clamp(h.t / 0.5, 0, 1);
  if (h.w > 0) {
    const open = clamp(1 - h.w / warning, 0, 1);
    const pulse = 1 + 0.08 * Math.sin(now / 70);
    ctx.save();
    ctx.setLineDash([8, 8]);
    ctx.lineDashOffset = -now / 30;
    ctx.strokeStyle = `rgba(199,155,255,${0.35 + 0.35 * Math.abs(Math.sin(now / 160))})`;
    ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.arc(h.x, h.y, (h.near || 80) * 1.4, 0, Math.PI * 2); ctx.stroke();
    ctx.restore();
    drawHoleAt(h.x, h.y, core * 1.6 * (0.15 + 0.85 * open) * pulse, now, 0.5 + 0.5 * open);
    if (!isMe(h.i)) text("GET AWAY!", 16, "#e6d4ff", h.x, h.y - (h.near || 80) * 1.4 - 14, { weight: 900, alpha: 0.6 + 0.4 * Math.abs(Math.sin(now / 120)) });
    return;
  }
  drawHoleAt(h.x, h.y, core * 1.6 * (0.3 + 0.7 * fade), now);
}

// --- swarm copies ---------------------------------------------------------------
// st.copies: [[owner, x, y, heavy]]: they look just like their owner
function drawCopies(st, R) {
  for (const [o, x, y, heavy] of st.copies || []) {
    const slot = app.match.slots[o];
    if (!slot) continue;
    ctx.globalAlpha = 0.88;
    drawPlayer(x, y, R, heavy, slot.color, slot.pattern, "none");
    ctx.globalAlpha = 1;
  }
}

// A bomb going off: a flash, a blast ring as big as what it knocks out,
// and smoke
function boomEffect(x, y, blast) {
  fx.burst(x, y, BLAST_COLOR, 40, 12, 6, 0.8);
  fx.burst(x, y, "#ef5350", 24, 8, 5, 0.6);
  fx.burst(x, y, "#5b647a", 20, 4, 9, 1.2, false);
  fx.booms.push({ x, y, r: blast, at: performance.now() });
  fx.kick(18);
}

function drawBooms(now) {
  fx.booms = fx.booms.filter((b) => now - b.at < 600);
  for (const b of fx.booms) {
    const k = (now - b.at) / 600;
    ctx.globalAlpha = (1 - k) * 0.55;
    circle(b.x, b.y, b.r * (0.4 + 0.6 * Math.sqrt(k)), k < 0.15 ? "#fff6d5" : BLAST_COLOR);
    ctx.globalAlpha = 1 - k;
    ctx.beginPath(); ctx.arc(b.x, b.y, b.r * (0.5 + 0.6 * k), 0, Math.PI * 2);
    ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 4 * (1 - k); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}
