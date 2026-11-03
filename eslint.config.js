// ESLint for the browser client (npm run lint; CI runs it).
//
// The client is plain scripts that share one global scope (index.html loads
// them in order), so a name one file declares at the top level is used by the
// others. ESLint can't know that, so this reads each file's top-level names
// and tells ESLint about them: a typo or a name nobody declares is still an
// error.
"use strict";
const fs = require("fs");
const path = require("path");
const js = require("@eslint/js");
const globals = require("globals");

const STATIC = path.join(__dirname, "bonk_game", "server", "static");
const CLIENT = fs.readdirSync(path.join(STATIC, "js")).map((f) => path.join(STATIC, "js", f))
  .filter((f) => f.endsWith(".js"));
// The UMD files (also used by Node in tests) put one name on window
const SHARED = ["predict.js", "netsim.js", "clock.js", "profile.js", "delta.js"].map((f) => path.join(STATIC, f));

const declared = {};
for (const f of CLIENT) {
  const src = fs.readFileSync(f, "utf8");
  for (const m of src.matchAll(/^(?:function|async function|class)\s+([A-Za-z_$][\w$]*)/gm)) declared[m[1]] = "writable";
  // const a = 1, b = 2; (several on one line too)
  for (const m of src.matchAll(/^(?:const|let|var)\s+(.*)$/gm)) {
    for (const d of m[1].matchAll(/(?:^|,)\s*([A-Za-z_$][\w$]*)\s*=/g)) declared[d[1]] = "writable";
  }
  // window.name = ... (for tests and the console)
  for (const m of src.matchAll(/window\.([A-Za-z_$][\w$]*)\s*=/g)) declared[m[1]] = "writable";
}
for (const f of SHARED) {
  const m = fs.readFileSync(f, "utf8").match(/root\.(Bonk\w+)\s*=/);
  if (m) declared[m[1]] = "readonly";
}

const rules = {
  ...js.configs.recommended.rules,
  "no-unused-vars": ["error", { vars: "local", args: "none", caughtErrors: "none" }],
  "no-empty": ["error", { allowEmptyCatch: true }],
};

module.exports = [
  { ignores: ["node_modules/**", "agents/**"] },
  {
    // The client scripts: browser, sharing one global scope
    files: ["bonk_game/server/static/js/**/*.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: { ...globals.browser, ...declared } },
    rules: { ...rules, "no-redeclare": "off" },
  },
  {
    // Files used both in the browser and in Node (UMD)
    files: ["bonk_game/server/static/*.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: { ...globals.browser, ...globals.node } },
    rules,
  },
  {
    files: ["tests/**/*.js", "eslint.config.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "commonjs", globals: { ...globals.node } },
    rules,
  },
  {
    // Code in tests that runs inside the page (page.evaluate)
    files: ["tests/web/**/*.js"],
    languageOptions: { globals: { ...globals.browser, ...declared } },
  },
];
