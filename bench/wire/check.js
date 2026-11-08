// node bench/wire/check.js results/fixtures.jsonl: the JS decoder
// (proto.js) gives exactly what JSON.parse gives for every recorded
// message, and the states delta.js rebuilds from each are the same.
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const { decode } = require("./proto.js");
const { apply } = require("../../bonk_game/server/static/delta.js");

const lines = fs.readFileSync(process.argv[2], "utf8").trim().split("\n").map((l) => JSON.parse(l));
let n = 0, scenario = null, a = null, b = null;
for (const f of lines) {
  if (f.scenario !== scenario) { scenario = f.scenario; a = b = null; }
  const want = JSON.parse(f.json);
  const raw = Buffer.from(f.bin, "base64");
  const got = decode(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.length));
  assert.deepStrictEqual(got, want, `${scenario} tick ${want.tick}`);
  for (const m of [got, want]) delete m.you;
  a = got.type === "state" ? got : apply(a, got);
  b = want.type === "state" ? want : apply(b, want);
  assert.ok(a && b, `${scenario} tick ${want.tick}: a delta didn't apply`);
  assert.deepStrictEqual(a, b, `${scenario} tick ${want.tick}: rebuilt state differs`);
  n += 1;
}
console.log(`JS: ${n} messages decode to exactly what JSON.parse gives, and rebuild exactly the same states`
  + ` (${path.basename(process.argv[2])})`);
