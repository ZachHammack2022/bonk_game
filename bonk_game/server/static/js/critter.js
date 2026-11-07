// The critters: every ball has a face. Eyes look where it's going, it
// squints and frowns when heavy, winces when bumped, gets scared falling
// fast, blinks now and then, and squashes and stretches (only how it's drawn:
// the physics ball stays round).
//
// critterFace(key, x, y, heavy, now) keeps a little memory per ball (its
// speed, the last bump) and says how to draw it; drawCritter draws it.
// critterHit(x, y, strength) is called on a "hit" event (effects.js).

const CRITTER_INK = "#3b2c52";
const critterMem = new Map();  // key -> {x, y, vx, vy, t, kick, kickAt, kickAngle, ouch, blinkAt}

function critterFace(key, x, y, heavy, now) {
  let m = critterMem.get(key);
  if (!m || now - m.t > 250) {
    m = { x, y, vx: 0, vy: 0, t: now, kick: 0, kickAt: -1e9, kickAngle: 0, ouch: -1e9,
          blinkAt: now + 1500 + Math.random() * 3000 };
    critterMem.set(key, m);
  }
  const dt = Math.max(1, now - m.t) / 1000;
  if (now > m.t) {
    const vx = (x - m.x) / dt, vy = (y - m.y) / dt;
    // Landing: was falling fast, now isn't: squash flat
    if (m.vy > 260 && vy < 60) critterKick(m, now, Math.min(0.3, m.vy / 1600), Math.PI / 2);
    const k = Math.min(1, dt * 14);
    m.vx += (vx - m.vx) * k; m.vy += (vy - m.vy) * k;
    m.x = x; m.y = y; m.t = now;
  }
  const speed = Math.hypot(m.vx, m.vy);
  const look = Math.min(1, speed / 320);
  const face = {
    lx: speed > 1 ? (m.vx / speed) * look : 0,
    ly: speed > 1 ? (m.vy / speed) * look * 0.7 : 0,
    mood: "happy", sx: 1, sy: 1, rot: 0, blink: false,
  };
  if (now - m.ouch < 380) face.mood = "ouch";
  else if (heavy > 0.5) face.mood = "heavy";
  else if (m.vy > 560) face.mood = "scared";
  if (now > m.blinkAt) {
    if (now - m.blinkAt < 130) face.blink = true;
    else m.blinkAt = now + 2200 + Math.random() * 3500;
  }
  // Squash after a bump or a landing (a quick wobble), else stretch with speed
  const age = (now - m.kickAt) / 1000;
  const wob = m.kick * Math.exp(-age * 9) * Math.cos(age * 38);
  if (Math.abs(wob) > 0.01) {
    face.rot = m.kickAngle; face.sx = 1 - wob; face.sy = 1 + wob * 0.8;
  } else if (speed > 150) {
    const s = Math.min(0.13, (speed - 150) / 4500);
    face.rot = Math.atan2(m.vy, m.vx); face.sx = 1 + s; face.sy = 1 - s * 0.8;
  }
  if (heavy > 0.5 && face.sx === 1) { face.rot = Math.PI / 2; face.sx = 0.94; face.sy = 1.04; }  // braced
  return face;
}

function critterKick(m, now, amount, angle) {
  m.kick = amount; m.kickAt = now; m.kickAngle = angle;
}

// Someone got bumped at (x, y): the balls touching there wince and squash
function critterHit(x, y, strength) {
  const now = performance.now();
  const near = [...critterMem.values()]
    .map((m) => [m, Math.hypot(m.x - x, m.y - y)])
    .filter(([m, d]) => d < 70 && now - m.t < 200)
    .sort((a, b) => a[1] - b[1]).slice(0, 2);
  for (const [m] of near) {
    m.ouch = now;
    critterKick(m, now, Math.min(0.32, 0.1 + strength / 60), Math.atan2(m.y - y, m.x - x));
  }
}

// Forget everyone (a new match)
function critterReset() { critterMem.clear(); }

// A ball with a face on any canvas context. face: from critterFace (or
// null: happy, looking ahead, as in the lobby and pickers).
function drawCritter(g, x, y, r, heavy, color, pattern = "plain", shadow = true, hat = "none", face = null) {
  face = face || { lx: 0.25, ly: 0, mood: "happy", sx: 1, sy: 1, rot: 0, blink: false };
  const dot = (cx, cy, rr, c) => { g.beginPath(); g.arc(cx, cy, Math.max(0.4, rr), 0, Math.PI * 2); g.fillStyle = c; g.fill(); };
  if (shadow) {
    g.fillStyle = "rgba(90,60,130,0.16)";
    g.beginPath(); g.ellipse(x + 2, y + r * 0.22 + 3, r * face.sx, r * face.sy, 0, 0, Math.PI * 2); g.fill();
  } else r -= 1;
  const fill = mix(color, darken(color, 0.22), heavy);
  const rim = darken(color, 0.32 + 0.12 * heavy);

  // The body, squashed or stretched along face.rot
  g.save();
  g.translate(x, y);
  g.rotate(face.rot); g.scale(face.sx, face.sy); g.rotate(-face.rot);
  dot(0, 0, r, rim);
  const ri = r - Math.max(1.2, r * 0.07) - heavy * r * 0.12;
  dot(0, 0, ri, fill);
  g.save();
  g.beginPath(); g.arc(0, 0, ri, 0, Math.PI * 2); g.clip();
  if (pattern && pattern !== "plain" && pattern !== "eyes" && pattern !== "smile") {
    g.globalAlpha *= 0.8;
    drawPattern(g, 0, 0, ri, pattern, fill);
    g.globalAlpha /= 0.8;
  }
  // Soft shading: a darker belly and a shine up top
  g.fillStyle = darken(fill, 0.1);
  g.beginPath(); g.arc(0, ri * 0.55, ri * 1.05, 0, Math.PI * 2); g.globalAlpha *= 0.55; g.fill(); g.globalAlpha /= 0.55;
  g.restore();
  g.fillStyle = "rgba(255,255,255,0.55)";
  g.beginPath(); g.ellipse(-r * 0.36, -r * 0.5, r * 0.26, r * 0.14, -0.5, 0, Math.PI * 2); g.fill();
  if (r >= 5) critterFeatures(g, r, fill, face, pattern);
  g.restore();
  if (hat && hat !== "none") drawHat(g, x, y, r, hat);
}

function critterFeatures(g, r, fill, face, pattern) {
  const dot = (cx, cy, rr, c) => { g.beginPath(); g.arc(cx, cy, Math.max(0.4, rr), 0, Math.PI * 2); g.fillStyle = c; g.fill(); };
  const lum = (() => { const [a, b, c] = rgb(fill); return (0.299 * a + 0.587 * b + 0.114 * c) / 255; })();
  const ink = lum < 0.4 ? "#fffaf2" : CRITTER_INK;
  const big = pattern === "eyes";                  // the "Eyes" pattern: big googly eyes
  const L = face.lx * r * 0.14, U = face.ly * r * 0.1;
  const ex = r * (big ? 0.36 : 0.32), ey = -r * 0.12 + U;
  g.strokeStyle = ink; g.fillStyle = ink; g.lineCap = "round"; g.lineJoin = "round";
  g.lineWidth = Math.max(1.1, r * 0.1);
  // Cheeks
  if (r >= 9) {
    g.fillStyle = "rgba(255,110,150,0.38)";
    for (const s of [-1, 1]) { g.beginPath(); g.ellipse(s * r * 0.56 + L * 0.6, r * 0.2 + U, r * 0.15, r * 0.09, 0, 0, Math.PI * 2); g.fill(); }
  }
  // Eyes
  for (const s of [-1, 1]) {
    const cx = s * ex + L;
    if (face.mood === "ouch") {             // > <
      g.beginPath();
      g.moveTo(cx - s * r * 0.13, ey - r * 0.11); g.lineTo(cx + s * r * 0.07, ey); g.lineTo(cx - s * r * 0.13, ey + r * 0.11);
      g.stroke();
    } else if (face.blink) {
      g.beginPath(); g.moveTo(cx - r * 0.12, ey + r * 0.02); g.quadraticCurveTo(cx, ey + r * 0.09, cx + r * 0.12, ey + r * 0.02); g.stroke();
    } else if (face.mood === "heavy") {     // a determined squint under a frown
      g.beginPath(); g.moveTo(cx - r * 0.15, ey - r * 0.14 - s * r * 0.06); g.lineTo(cx + r * 0.15, ey - r * 0.14 + s * r * 0.06); g.stroke();
      dot(cx + L * 0.3, ey + r * 0.04, r * 0.085, ink);
    } else {
      const er = r * (big ? 0.23 : face.mood === "scared" ? 0.2 : 0.16);
      g.fillStyle = "#ffffff";
      g.beginPath(); g.ellipse(cx, ey, er, er * (big ? 1 : 1.2), 0, 0, Math.PI * 2); g.fill();
      dot(cx + face.lx * er * 0.45, ey + face.ly * er * 0.4 + er * 0.1, er * (face.mood === "scared" ? 0.38 : 0.55), CRITTER_INK);
      if (r >= 10) dot(cx + face.lx * er * 0.45 - er * 0.2, ey - er * 0.15, er * 0.17, "#ffffff");
    }
  }
  // Mouth
  const my = r * 0.3 + U;
  g.strokeStyle = ink; g.fillStyle = ink;
  g.beginPath();
  switch (face.mood) {
    case "ouch": g.ellipse(L, my + r * 0.04, r * 0.12, r * 0.1, 0, 0, Math.PI * 2); g.fill(); break;
    case "scared": g.ellipse(L, my + r * 0.02, r * 0.08, r * 0.12, 0, 0, Math.PI * 2); g.fill(); break;
    case "heavy": g.moveTo(L - r * 0.16, my + r * 0.02); g.lineTo(L + r * 0.16, my - r * 0.02); g.stroke(); break;
    default:
      if (pattern === "smile") { g.arc(L, my - r * 0.08, r * 0.3, 0.12 * Math.PI, 0.88 * Math.PI); g.closePath(); g.fill(); }
      else { g.arc(L, my - r * 0.1, r * 0.18, 0.18 * Math.PI, 0.82 * Math.PI); g.stroke(); }
  }
}
