// Browser test for the web version: two players, a full match, a reload
// mid-match, results, back to the lobby, and a phone joining by code.
//
//   pip install -r requirements-server.txt
//   npm install --no-save playwright && npx playwright install chromium
//   node tests/web/e2e.js
//
// Starts its own server on a free port. Set E2E_SHOTS=<dir> to save
// screenshots. Exits non-zero on any failure or page error.
"use strict";
const { spawn } = require("child_process");
const fs = require("fs");
const net = require("net");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..", "..");
const SHOTS = process.env.E2E_SHOTS;
const PY = process.env.PYTHON || "python3";

function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

async function waitForServer(base, proc) {
  for (let i = 0; i < 100; i++) {
    if (proc.exitCode !== null) throw new Error("server exited early");
    try { if ((await fetch(base + "/healthz")).ok) return; } catch (e) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("server didn't start");
}

function check(cond, what) {
  if (!cond) throw new Error("check failed: " + what);
  console.log("ok -", what);
}

(async () => {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(PY, ["-m", "bonk_game.server", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: ROOT, env: { ...process.env, PYTHONPATH: ROOT }, stdio: ["ignore", "inherit", "inherit"] });
  const errors = [];
  let browser;
  const shot = async (page, name) => {
    if (!SHOTS) return;
    fs.mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: path.join(SHOTS, name + ".png") });
  };
  try {
    await waitForServer(base, server);
    browser = await chromium.launch();
    const open = async (name, opts = { viewport: { width: 1000, height: 720 } }) => {
      const page = await (await browser.newContext(opts)).newPage();
      page.on("pageerror", (e) => errors.push(`${name}: ${e.message}`));
      page.on("console", (m) => { if (m.type() === "error") errors.push(`${name}: ${m.text()}`); });
      return page;
    };

    // Host makes a room
    const host = await open("host");
    await host.goto(base + "/");
    await host.fill("#name", "Ann");
    await host.click("#create");
    await host.waitForSelector("#lobby:not(.hidden)");
    const url = host.url();
    check(/\/r\/[A-Z]{4}$/.test(url), "creating a room opens its link");

    // A friend opens the link: asked for a name, then joins
    const guest = await open("guest");
    await guest.goto(url);
    await guest.fill("#name", "Bob");
    await guest.click("#join-form button");
    await guest.waitForSelector("#lobby:not(.hidden)");
    await host.waitForFunction(() => document.querySelectorAll("#seats .seat").length === 3);
    check(true, "the guest shows up in the host's lobby");
    check(await guest.isHidden("#start"), "only the host sees Start");

    // The guest picks green
    await guest.click("#seats .seat.you .ball");
    await guest.click(".picker .swatch[title=Green]");
    await host.waitForFunction(() => bonkDebug.app.lobby.seats[1].color === 5);
    check(true, "picking a colour shows up for everyone");

    // Host sets up a quick match
    await host.selectOption("#map", "classic");
    await host.selectOption("#first-to", "1");
    await host.click("#add-bot");
    await host.waitForFunction(() => document.querySelectorAll("#seats .seat").length === 4);
    await guest.waitForFunction(() => document.querySelector("#map").value === "classic");
    check(true, "settings reach the guest");
    await shot(host, "lobby");

    await host.click("#start");
    await host.waitForSelector("#game:not(.hidden)");
    await guest.waitForSelector("#game:not(.hidden)");
    check(true, "both players go to the match");
    await host.waitForTimeout(2200);
    await guest.keyboard.down("ArrowRight");
    await guest.keyboard.press("Digit2");
    await host.waitForFunction(() => bonkDebug.fx.emotes.some((e) => e.slot === 1 && e.id === 1), null, { timeout: 3000 });
    check(true, "an emote reaches the other player");
    await host.waitForTimeout(150);
    await shot(guest, "match");
    await guest.keyboard.up("ArrowRight");
    check(await guest.evaluate(() => bonkDebug.app.match.slots[1].color_name) === "Green", "the match uses the picked colour");

    // The guest reloads mid-match and gets their seat back
    await guest.reload();
    const back = await guest.waitForSelector("#game:not(.hidden)", { timeout: 8000 }).then(() => true, () => false);
    // (the match may already have ended; then they land on results/lobby)
    check(back || (await guest.isVisible("#lobby")), "a reload puts the guest back in the room");

    await host.waitForSelector("#results:not(.hidden)", { timeout: 120000 });
    const winner = await host.textContent("#winner");
    check(/wins?!|Draw!/.test(winner), `results show a winner (${winner.trim()})`);
    await shot(host, "results");

    // Everyone votes for a rematch
    await guest.waitForSelector("#results:not(.hidden)");
    await host.click("#vote");
    await guest.waitForFunction(() => /1\/2/.test(document.querySelector("#vote").textContent));
    await guest.click("#vote");
    await host.waitForSelector("#results.hidden", { state: "attached" });
    await host.waitForFunction(() => bonkDebug.app.match && !bonkDebug.app.results);
    check(true, "a rematch starts once everyone votes");
    await host.waitForSelector("#results:not(.hidden)", { timeout: 120000 });
    await host.click("#to-lobby");
    await host.waitForSelector("#lobby:not(.hidden)");
    await guest.waitForSelector("#lobby:not(.hidden)");
    check(true, "back to the lobby together");

    // A phone joins by typing the code
    const phone = await open("phone", { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    await phone.goto(base + "/");
    await phone.fill("#name", "Cat");
    await phone.fill("#code", url.split("/r/")[1].toLowerCase());
    await phone.click("#join-form button");
    await phone.waitForSelector("#lobby:not(.hidden)");
    const wide = await phone.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    check(!wide, "the lobby fits a phone screen");
    await shot(phone, "phone-lobby");

    // The host removes the phone
    host.once("dialog", (d) => d.accept());
    await host.waitForFunction(() => document.querySelectorAll("#seats .remove").length >= 2);
    await host.evaluate(() => {
      const seat = [...document.querySelectorAll("#seats .seat")].find((li) => li.textContent.includes("Cat"));
      seat.querySelector(".remove").click();
    });
    await phone.waitForSelector("#home:not(.hidden)");
    check((await phone.textContent("#toast")).includes("removed"), "a removed player is sent away");
    await host.waitForFunction(() => !document.querySelector("#seats").textContent.includes("Cat"));
    check(true, "and disappears from the lobby");

    // A room that doesn't exist
    const lost = await open("lost");
    await lost.goto(base + "/");
    await lost.fill("#name", "Dan");
    await lost.fill("#code", "ZZZZ");
    await lost.click("#join-form button");
    await lost.waitForSelector("#toast:not(.hidden)");
    check((await lost.textContent("#toast")).includes("doesn't exist"), "a bad code says so");

    check(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch((e) => { console.error(e); process.exit(1); });
