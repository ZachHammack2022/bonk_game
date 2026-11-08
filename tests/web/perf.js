// How much each frame costs in the browser, on a phone: plays a real match
// in Chromium as an iPhone (3x screen, landscape) with the CPU slowed down
// and a pretend network (static/netsim.js), and prints a table.
//
//   node tests/web/perf.js [--maps classic,grand,platform] [--seconds 8] [--lag 150]
//                          [--throttle 4] [--runs 1] [--base http://127.0.0.1:8000]
//
// Without --base it starts its own server from this checkout. To compare
// two versions, run a server from each (say main on one port, your branch
// on another) and point --base at each.
//
// Your ball has to be in play for prediction to be measured, so: it's
// Knockouts mode (a knocked-out ball comes straight back, instead of
// sitting out the round), against three Easy bots, and your ball steers
// for the middle of the map (wandering left and right, and up and down
// where you can fly), hopping now and then, so its buttons keep changing.
// Timings are of frames where your ball was in play (predicted), and it
// measures until it has --seconds of those (giving up after four times
// that, and saying so).
//
// Not run in CI (it takes a while, and timings depend on the machine).
"use strict";
const { spawn } = require("child_process");
const net = require("net");
const path = require("path");
const { chromium, devices } = require("playwright");

const ROOT = path.resolve(__dirname, "..", "..");
const PY = process.env.PYTHON || "python3";
const arg = (name, d) => {
  const i = process.argv.indexOf("--" + name);
  return i > 0 ? process.argv[i + 1] : d;
};
const MAPS = arg("maps", "classic,grand,platform").split(",");
const SECONDS = +arg("seconds", 8);
const LAG = +arg("lag", 150);
const THROTTLE = +arg("throttle", 4);
const RUNS = +arg("runs", 1);

const freePort = () => new Promise((resolve) => {
  const s = net.createServer();
  s.listen(0, () => { const { port } = s.address(); s.close(() => resolve(port)); });
});

async function waitForServer(base) {
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(base + "/healthz")).ok) return; } catch (e) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server didn't start");
}

// Make a room, set it up and start: you and three Easy bots
async function startMatch(page, base, map) {
  await page.goto(base + "/" + (LAG ? `?lag=${LAG}&jitter=20&seed=1` : ""));
  await page.click("#find");
  await page.waitForSelector("#browse:not(.hidden)");
  await page.click("#new-game");
  await page.waitForSelector("#new-dialog:not(.hidden)");
  await page.click("#new-create");
  await page.waitForSelector("#lobby:not(.hidden)");
  await page.evaluate((map) => {
    send({ type: "settings", map, mode: "knockouts", first_to: 5, bots: ["bot:easy", "bot:easy", "bot:easy"] });
  }, map);
  await page.waitForFunction((map) => document.querySelector("#map").value === map, map);
  await page.evaluate(() => send({ type: "start" }));
  await page.waitForSelector("#game:not(.hidden)");
}

// Steer for the middle of the map until stop() is called
function autopilot(page) {
  let on = true;
  const held = new Set();
  const hold = async (key, down) => {
    if (down === held.has(key)) return;
    if (down) { held.add(key); await page.keyboard.down(key); } else { held.delete(key); await page.keyboard.up(key); }
  };
  const done = (async () => {
    const t0 = Date.now();
    while (on) {
      const s = await page.evaluate(() => {
        const d = bonkDebug.drawn;
        return d && { x: d.x, y: d.y, W, H, fly: !!(app.match && app.match.physics.can_fly) };
      }).catch(() => null);
      const t = (Date.now() - t0) / 1000;
      if (s) {
        const tx = s.W / 2 + 110 * Math.sin(t * 1.3);  // wander left and right of the middle
        await hold("ArrowRight", s.x < tx - 15);
        await hold("ArrowLeft", s.x > tx + 15);
        if (s.fly) {
          const ty = s.H / 2 + 60 * Math.sin(t * 0.9);
          await hold("ArrowUp", s.y > ty + 15);
          await hold("ArrowDown", s.y < ty - 15);
        } else {
          await hold("ArrowUp", Math.floor(t / 0.8) % 2 === 0 && t % 0.8 < 0.15);  // a hop now and then
        }
      }
      await page.waitForTimeout(80);
    }
    for (const k of [...held]) await hold(k, false);
  })();
  return { stop: () => { on = false; return done; } };
}

// Time frames until `seconds` of them had your ball in play (or four times
// that has gone by): the whole frame and predicting your ball, for those
function measure(page, seconds) {
  return page.evaluate((seconds) => new Promise((resolve) => {
    const origFrame = window.frame, origOwn = window.ownPosition;
    // (frame() asks for the next frame itself, through the global name, so
    // replacing window.frame is enough to see every frame)
    let frames = 0, inPlay = 0, inPlayMs = 0, total = 0, predicting = 0, predicted = false, last = 0, done = false;
    const start = performance.now();
    window.ownPosition = function (...a) {
      const t0 = performance.now();
      const r = origOwn.apply(this, a);
      if (r) { predicted = true; predicting += performance.now() - t0; }
      return r;
    };
    window.frame = (now) => {
      if (done) return origFrame(now);
      predicted = false;
      const t0 = performance.now();
      origFrame(now);
      const cost = performance.now() - t0;
      frames += 1;
      if (predicted) {
        inPlay += 1; total += cost;
        if (last) inPlayMs += now - last;
      }
      last = predicted ? now : 0;
      const elapsed = performance.now() - start;
      if (inPlayMs >= seconds * 1000 || elapsed >= seconds * 4000) {
        done = true;
        window.frame = origFrame; window.ownPosition = origOwn;
        resolve({
          enough: inPlayMs >= seconds * 1000,
          fps: inPlayMs ? (inPlay - 1) * 1000 / inPlayMs : 0,
          frameMs: inPlay ? total / inPlay : null,
          predictMs: inPlay ? predicting / inPlay : null,
          inPlayShare: inPlay / Math.max(1, frames),
        });
      }
    };
  }), seconds);
}

async function run(browser, base, map) {
  const context = await browser.newContext({ ...devices["iPhone 13 landscape"] });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    await startMatch(page, base, map);
    await page.waitForTimeout(3000);  // (the countdown, and the clock settling)
    const cdp = await context.newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: THROTTLE });
    const pilot = autopilot(page);
    const r = await measure(page, SECONDS);
    await pilot.stop();
    if (errors.length) throw new Error(`${map}: ${errors.join(" | ")}`);
    return r;
  } finally {
    await context.close();
  }
}

(async () => {
  let base = arg("base", null), server = null;
  if (!base) {
    const port = await freePort();
    base = `http://127.0.0.1:${port}`;
    server = spawn(PY, ["-m", "bonk_game.server", "--host", "127.0.0.1", "--port", String(port)],
      { cwd: ROOT, env: { ...process.env, PYTHONPATH: ROOT }, stdio: "ignore" });
  }
  let browser;
  try {
    await waitForServer(base);
    browser = await chromium.launch();
    const rows = [];
    for (const map of MAPS) {
      for (let k = 0; k < RUNS; k++) {
        const r = await run(browser, base, map);
        const ms = (v) => (v == null ? "–" : v.toFixed(2) + " ms");
        rows.push([map, r.fps.toFixed(1), ms(r.frameMs), ms(r.predictMs),
          `${Math.round(r.inPlayShare * 100)}%${r.enough ? "" : " (not enough in play: not reliable)"}`]);
        console.error(`${map}: done`);
      }
    }
    console.log(`iPhone 13 landscape, CPU ${THROTTLE}x slower, ${LAG} ms simulated lag, Knockouts with 3 Easy bots, ${SECONDS} s of your ball in play per run:\n`);
    console.log("| map | fps | script per frame | predicting your ball | time in play |");
    console.log("|---|---|---|---|---|");
    for (const row of rows) console.log("| " + row.join(" | ") + " |");
  } finally {
    if (browser) await browser.close();
    if (server) server.kill();
  }
})().catch((e) => { console.error(e); process.exit(1); });
