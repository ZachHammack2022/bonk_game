// The phone side of the wire benchmark (bench/wire/bench.py): how long the
// browser's main thread takes to turn each state message into a state:
// JSON.parse vs the prototype binary decoder (bench/wire/proto.js), then
// delta.js either way. In Chromium as an iPhone, with the CPU slowed down.
//
//   python -m bench.wire.bench check          # (writes the recorded messages)
//   node tests/web/wire_bench.js [--throttle 4] [--rounds 15]
//
// (Decompressing permessage-deflate happens in the browser's network code,
// off the main thread, so it isn't in these numbers either way.)
"use strict";
/* global WireProto */
const fs = require("fs");
const path = require("path");
const { chromium, devices } = require("playwright");

const ROOT = path.resolve(__dirname, "..", "..");
const arg = (name, d) => {
  const i = process.argv.indexOf("--" + name);
  return i > 0 ? process.argv[i + 1] : d;
};
const THROTTLE = +arg("throttle", 4);
const ROUNDS = +arg("rounds", 15);
const FIXTURES = path.join(ROOT, "bench", "wire", "results", "fixtures.jsonl");

(async () => {
  const lines = fs.readFileSync(FIXTURES, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const scenarios = {};
  for (const f of lines) (scenarios[f.scenario] = scenarios[f.scenario] || []).push(f);
  const browser = await chromium.launch();
  const context = await browser.newContext({ ...devices["iPhone 13 landscape"] });
  const page = await context.newPage();
  await page.goto("about:blank");
  await page.addScriptTag({ path: path.join(ROOT, "bonk_game", "server", "static", "delta.js") });
  await page.addScriptTag({ path: path.join(ROOT, "bench", "wire", "proto.js") });
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: THROTTLE });
  const rows = [];
  for (const [name, fs_] of Object.entries(scenarios)) {
    const r = await page.evaluate(({ msgs, rounds }) => {
      const texts = msgs.map((m) => m.json);
      const bufs = msgs.map((m) => {
        const s = atob(m.bin), b = new Uint8Array(s.length);
        for (let i = 0; i < s.length; i++) b[i] = s.charCodeAt(i);
        return b.buffer;
      });
      const run = (decode, items) => {
        let state = null;
        const t0 = performance.now();
        for (const it of items) {
          const msg = decode(it);
          state = msg.type === "state" ? msg : BonkDelta.apply(state, msg);
        }
        if (!state) throw new Error("no state");
        return (performance.now() - t0) * 1000 / items.length;  // us per message
      };
      const out = { json: [], bin: [] };
      for (let k = 0; k <= rounds; k++) {
        const order = k % 2 ? ["json", "bin"] : ["bin", "json"];
        for (const v of order) {
          const us = v === "json" ? run(JSON.parse, texts) : run(WireProto.decode, bufs);
          if (k) out[v].push(us);  // (round 0 warms up)
        }
      }
      const med = (xs) => xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)];
      return { json: med(out.json), bin: med(out.bin), jsonMax: Math.max(...out.json), binMax: Math.max(...out.bin) };
    }, { msgs: fs_, rounds: ROUNDS });
    rows.push([name, r]);
    console.error(`${name}: done`);
  }
  await browser.close();
  console.log(`iPhone 13 landscape in Chromium, CPU ${THROTTLE}x slower; turning a message into a state`
    + ` (decode + delta.js), median of ${ROUNDS} rounds over ${lines.length / rows.length} recorded messages each:\n`);
  console.log("| scenario | JSON.parse | binary decode | per second of play (30 messages), JSON → binary |");
  console.log("|---|---|---|---|");
  for (const [name, r] of rows) {
    console.log(`| ${name} | ${r.json.toFixed(1)} µs | ${r.bin.toFixed(1)} µs | `
      + `${(r.json * 30 / 1000).toFixed(2)} → ${(r.bin * 30 / 1000).toFixed(2)} ms |`);
  }
})().catch((e) => { console.error(e); process.exit(1); });
