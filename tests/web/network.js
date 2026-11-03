// How the game holds up on worse networks: plays a real match in a real
// browser on each pretend network (static/netsim.js) and prints what the
// playtest report saw (static/js/report.js).
//
//   node tests/web/network.js [--seconds 30] [--map platform] [--nets none,wifi,mobile,far,bad]
//
// You play against two Hard bots, holding left/right and jumping in a
// fixed pattern. Each network uses the same seed, so runs are comparable.
// Not run in CI (it takes a while); the numbers go in the README.
"use strict";
const { spawn } = require("child_process");
const net = require("net");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..", "..");
const PY = process.env.PYTHON || "python3";
const arg = (name, d) => {
  const i = process.argv.indexOf("--" + name);
  return i > 0 ? process.argv[i + 1] : d;
};
const SECONDS = +arg("seconds", 30);
const MAP = arg("map", "platform");
const NETS = arg("nets", "none,wifi,mobile,far,bad").split(",");

const freePort = () => new Promise((resolve) => {
  const s = net.createServer();
  s.listen(0, () => { const { port } = s.address(); s.close(() => resolve(port)); });
});

async function waitForServer(base) {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(base + "/healthz")).ok) return; } catch (e) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server didn't start");
}

async function play(browser, base, netName) {
  const page = await (await browser.newContext({ viewport: { width: 1000, height: 720 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const q = netName === "none" ? "" : `?net=${netName}&seed=1`;
  await page.goto(base + "/" + q);
  await page.fill("#name", "Tester");
  await page.click("#create");
  await page.waitForSelector("#lobby:not(.hidden)");
  await page.evaluate((map) => {
    send({ type: "settings", map, first_to: 99, bots: ["bot:hard", "bot:hard"] });
    send({ type: "start" });
  }, MAP);
  await page.waitForSelector("#game:not(.hidden)");
  // Move about: run one way, jump, turn round, go heavy now and then
  const pattern = [["ArrowRight", 700], ["ArrowUp", 150], ["ArrowLeft", 900], ["Space", 300], ["ArrowUp", 150], ["ArrowRight", 500]];
  const end = Date.now() + SECONDS * 1000;
  for (let k = 0; Date.now() < end; k++) {
    const [key, ms] = pattern[k % pattern.length];
    await page.keyboard.down(key);
    await page.waitForTimeout(ms);
    await page.keyboard.up(key);
  }
  const r = await page.evaluate(() => { playtest.finish(); return playtest.pending; });
  await page.context().close();
  if (errors.length) throw new Error(netName + ": " + errors.join(" | "));
  return r;
}

(async () => {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(PY, ["-m", "bonk_game.server", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: ROOT, env: { ...process.env, PYTHONPATH: ROOT }, stdio: "ignore" });
  let browser;
  try {
    await waitForServer(base);
    browser = await chromium.launch();
    const rows = [];
    for (const n of NETS) {
      const r = await play(browser, base, n);
      const perMin = (x) => (x * 60) / r.seconds;
      rows.push([n, r.sim || "–", `${Math.round(r.ping.med)} / ${Math.round(r.ping.p95)} ms`,
        perMin(r.states.late).toFixed(1), `${Math.round(r.states.max_gap)} ms`,
        `${r.frames.frozen.toFixed(1)}%`, perMin(r.corrections.big).toFixed(1),
        perMin(r.corrections.huge).toFixed(1), `${Math.round(r.corrections.max)} px`]);
      console.error(`${n}: done`);
    }
    console.log(`You against 2 Hard bots on ${MAP}, ${SECONDS} s per network:\n`);
    console.log("| network | simulated | ping med / p95 | late states /min | worst gap | frames frozen | corrections >6 px /min | >20 px /min | worst correction |");
    console.log("|---|---|---|---|---|---|---|---|---|");
    for (const row of rows) console.log("| " + row.join(" | ") + " |");
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch((e) => { console.error(e); process.exit(1); });
