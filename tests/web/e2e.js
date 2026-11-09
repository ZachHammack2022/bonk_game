// Browser test for the web version: two players, a full match, a reload
// mid-match, results, back to the lobby, a phone joining by code, and the
// server restarting for an update.
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
  const startServer = () => spawn(PY, ["-m", "bonk_game.server", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: ROOT, env: { ...process.env, PYTHONPATH: ROOT }, stdio: ["ignore", "inherit", "inherit"] });
  let server = startServer();
  let restarting = false;  // (the browser logs failed reconnects while the server is down)
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
    // csp: keep the page's Content-Security-Policy. Most pages bypass it,
    // as waitForFunction polls with eval, which the policy forbids; the
    // "strict" page below plays with it on.
    const open = async (name, opts = { viewport: { width: 1000, height: 720 } }, csp = false) => {
      const page = await (await browser.newContext({ ...opts, bypassCSP: !csp })).newPage();
      page.on("pageerror", (e) => errors.push(`${name}: ${e.message}`));
      page.on("console", (m) => {
        if (m.type() !== "error") return;
        if (restarting && /WebSocket|ERR_CONNECTION_REFUSED/.test(m.text())) return;
        errors.push(`${name}: ${m.text()}`);
      });
      return page;
    };

    // Host sets up their ball and controls, then makes a room
    const host = await open("host");
    await host.goto(base + "/");
    await host.fill("#name", "Ann");
    await host.click("#edit-ball");
    await host.click("#profile-colors [title=Purple]");
    await host.click("#profile-patterns [data-pattern=stripes]");
    await host.waitForSelector("#profile-extras .looks-trail [data-look=sparkle].locked");
    check(await host.isVisible("#profile-extras .looks-hat [data-look=none].on") && !(await host.$("#profile-extras [data-look=halo].locked")),
      "trails, hats and knockout effects are in Customize: a few locked for guests (sign in), the rest free");
    await host.click("#profile-extras .looks-hat [data-look=halo]");
    check(await host.isVisible("#profile-extras .looks-hat [data-look=halo].on"), "a guest can wear the halo");
    await host.click("#profile-extras .looks-hat [data-look=none]");
    check(await host.isVisible('#me-tabs [data-tab="ball"].on'), "your ball opens your profile, on its Ball tab");
    await host.click("#me-tabs [data-tab=settings]");
    check(await host.isVisible("#set-keys") && await host.isHidden("#profile-colors"), "settings are a tab of your profile");
    await host.click("#me-done");
    check((await host.textContent("#home-ball-label")).includes("Purple"), "you can pick a favourite colour and pattern");
    await host.keyboard.press("Escape");
    await host.waitForSelector("#settings:not(.hidden)");
    await host.click("#set-keys [data-action=heavy]");
    await host.keyboard.press("KeyH");
    await host.keyboard.press("Escape");
    check(await host.evaluate(() => JSON.parse(localStorage.getItem("bonk.profile")).prefs.keys.heavy === "KeyH"), "keys can be rebound in settings");
    check(!(await host.$("#create")) && !(await host.isVisible("#join-form")) && await host.isVisible("#find"),
      "the start page has one way in: Play");
    await shot(host, "home");
    await host.click("#find");
    await host.waitForSelector("#browse:not(.hidden)");
    await host.click("#new-game");
    await host.waitForSelector("#new-dialog:not(.hidden)");
    const hostName = await host.inputValue("#name");
    check((await host.inputValue("#new-name")) === `${hostName}'s room`, "a new room is named after you, to start with");
    await shot(host, "new-game");
    check(await host.isVisible('#new-privacy [data-private="1"].on'), "new games are private unless you pick public");
    await host.click("#new-create");
    await host.waitForSelector("#lobby:not(.hidden)");
    const url = host.url();
    const password = new URL(url).searchParams.get("pw");
    check(/\/r\/[A-Z]{4}\?pw=[a-z0-9]{6}$/.test(url), "a private game's link has its password in it");
    check((await host.inputValue("#room-name-input")) === `${hostName}'s room` && (await host.textContent("#room-password")) === password &&
      await host.isVisible('#privacy [data-private="1"].on'), "the lobby shows the room's name, that it's private, and its password");
    const code = new URL(url).pathname.split("/r/")[1];
    await host.waitForFunction(() => bonkDebug.app.lobby && bonkDebug.app.lobby.seats[0].color === 3 && bonkDebug.app.lobby.seats[0].pattern === "stripes");
    check(true, "your ball's colour and pattern come with you into the room");

    // A friend opens the link: asked for a name, then joins
    const guest = await open("guest");
    // A pretend controller the test can press (navigator.getGamepads)
    await guest.addInitScript(() => {
      window.__pads = [];
      navigator.getGamepads = () => window.__pads;
    });
    await guest.goto(url);
    await guest.fill("#name", "Bob");
    check((await guest.textContent("#join-form button")).includes(code) && await guest.isHidden("#find"),
      "an invite link offers that game on the start page");
    await guest.click("#join-form button");
    await guest.waitForSelector("#lobby:not(.hidden)");
    check(true, "the invite link fills in the password");
    await host.waitForFunction(() => document.querySelectorAll("#seats .seat").length === 3);
    check(true, "the guest shows up in the host's lobby");
    check(await guest.isHidden("#start"), "only the host sees Start");

    // The guest picks green
    await guest.click("#seats .seat.you .ball");
    await guest.click(".picker .swatch[title=Green]");
    await host.waitForFunction(() => bonkDebug.app.lobby.seats[1].color === 5);
    check(true, "picking a colour shows up for everyone");

    // Host sets up a quick match (in the Game settings dialog)
    await host.click("#open-game-settings");
    // Dropdowns open a list in the page's own style (js/dropdown.js), not the browser's
    await host.click("#map");
    check(await host.isVisible(".dropdown-menu") && await host.locator(".dropdown-item.selected").count() === 1,
      "a dropdown opens the page's own list, with the chosen one ticked");
    await host.keyboard.press("Escape");
    check(await host.isHidden(".dropdown-menu") && await host.evaluate(() => document.activeElement.id) === "map",
      "Escape closes it, back on the dropdown");
    await host.click("#first-to");
    await host.click('.dropdown-item:text-is("1")');
    check(await host.isHidden(".dropdown-menu") && await host.inputValue("#first-to") === "1", "clicking an option picks it");
    await host.selectOption("#map", "classic");
    await host.selectOption("#first-to", "1");
    await host.click("#game-settings-done");
    check((await host.textContent("#sum-map")) === "Classic" && (await host.textContent("#sum-rest")).includes("First to 1"),
      "the lobby sums up the settings");
    // Map, mode and power-ups can be changed right on the lobby, no dialog
    check((await host.inputValue("#quick-map")) === "classic" && (await guest.isDisabled("#quick-map")),
      "the lobby's map dropdown follows the settings (the guest can't change it)");
    const powerWas = await host.isChecked("#quick-power-ups");
    await host.click("#quick-power-ups");
    await guest.waitForFunction((w) => document.querySelector("#quick-power-ups").checked === !w, powerWas);
    await host.click("#quick-power-ups");
    await guest.waitForFunction((w) => document.querySelector("#power-ups").checked === w, powerWas);
    check(true, "power-ups switch from the lobby, for everyone");
    // Just the two of them, no bots: nobody scores (and ends this first-to-1
    // match) until the guest rolls into a wall on purpose, after the checks
    // that need the match on
    await host.click('#seats [aria-label="Remove bot"]');
    await host.waitForFunction(() => document.querySelectorAll("#seats .seat").length === 2);
    await guest.waitForFunction(() => document.querySelector("#map").value === "classic");
    check(true, "settings reach the guest");
    await host.setViewportSize({ width: 1000, height: 585 });
    check(await host.evaluate(() => { const r = $("start").getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }),
      "Start is on screen in a smallish window, without scrolling");
    await host.setViewportSize({ width: 1000, height: 720 });
    // Chat in the lobby: everyone sees it, with swear words starred out
    await guest.fill("#chat-input", "hi there you shit");
    await guest.press("#chat-input", "Enter");
    await host.waitForFunction(() => document.querySelector("#chat-log").textContent.includes("hi there you ****"));
    check((await host.textContent("#chat-log")).includes("Bob joined"), "lobby chat reaches everyone, filtered, with who joined");
    await shot(host, "lobby");

    await host.click("#start");
    await host.waitForSelector("#game:not(.hidden)");
    await guest.waitForSelector("#game:not(.hidden)");
    check(true, "both players go to the match");
    await host.waitForTimeout(2200);
    await guest.keyboard.press("Digit2");
    await host.waitForFunction(() => bonkDebug.fx.emotes.some((e) => e.slot === 1 && e.id === 1), null, { timeout: 3000 });
    check(true, "an emote reaches the other player");
    // Chat over the match: Enter opens the box; typing doesn't move your ball
    await guest.keyboard.press("Enter");
    await guest.waitForSelector("#chat-game-input:focus");
    await guest.keyboard.type("wasd nice");
    check(await guest.evaluate(() => held.keys.size === 0), "typing in the match chat doesn't move your ball");
    await guest.keyboard.press("Enter");
    await host.waitForFunction(() => document.querySelector("#chat-feed").textContent.includes("wasd nice"));
    check(await guest.isHidden("#chat-game-form"), "match chat shows over the game, and the box closes after sending");
    await shot(guest, "match");

    // A controller: push the stick left, then let go
    await guest.bringToFront();
    await guest.evaluate(() => {
      const idle = Array.from({ length: 17 }, () => ({ pressed: false, value: 0 }));
      window.__pads = [{ id: "Test pad", buttons: idle, axes: [-1, 0, 0, 0] }];
    });
    await guest.waitForFunction(() => bonkDebug.net.inputs.at(-1).b.join("") === "01000");
    await guest.evaluate(() => { window.__pads[0].axes = [0, 0, 0, 0]; });
    await guest.waitForFunction(() => bonkDebug.net.inputs.at(-1).b.join("") === "00000");
    check(true, "a gamepad's stick moves your ball");
    check(await guest.evaluate(() => {
      const S = bonkDebug.app.last;
      return !!S && S.you.length === 3 && S.players.length === bonkDebug.app.match.slots.length;
    }), "the match is rebuilt from changes, with your own speeds");
    check(await guest.evaluate(() => bonkDebug.app.match.slots[1].color_name) === "Green", "the match uses the picked colour");
    check(await guest.evaluate(() => {
      prefs.colorblind = true; applyLooks(bonkDebug.app.match);
      const ps = bonkDebug.app.match.slots.map((x) => x.pattern);
      prefs.colorblind = false; applyLooks(bonkDebug.app.match);
      return new Set(ps).size === ps.length && !ps.includes("plain") && bonkDebug.app.match.slots[0].pattern === "stripes";
    }), "colourblind mode gives every ball a pattern of its own");

    // The guest reloads mid-match and gets their seat back
    await guest.reload();
    const back = await guest.waitForSelector("#game:not(.hidden)", { timeout: 8000 }).then(() => true, () => false);
    // (the match may already have ended; then they land on results/lobby)
    check(back || (await guest.isVisible("#lobby")), "a reload puts the guest back in the room");

    // The guest rolls into the deadly right wall (Classic): the host scores, and it's over
    await guest.keyboard.down("ArrowRight");
    await host.waitForSelector("#results:not(.hidden)", { timeout: 120000 });
    await guest.keyboard.up("ArrowRight");
    const winner = await host.textContent("#winner");
    check(/wins?!|Draw!/.test(winner), `results show a winner (${winner.trim()})`);
    await shot(host, "results");
    const res = await host.evaluate(() => bonkDebug.app.results);
    check(res.stats.length === res.slots.length && Array.isArray(res.awards), "results come with stats and awards");
    const shown = await host.$$eval("#awards li", (els) => els.length);
    check(shown === res.awards.length, `the awards are on the results screen (${shown})`);

    // Playtest reports go by themselves (sent when the next match starts):
    // nobody is asked how the match felt
    await guest.waitForSelector("#results:not(.hidden)");
    check(!(await host.$("#feel")), "the results screen doesn't ask how the match felt");
    await guest.evaluate(() => playtest.error("e2e test error", "e2e.js:1"));

    // The killcam plays the final knockout in slow motion; the match can be downloaded
    check(await host.isVisible("#killcam-btn"), "the results offer a killcam");
    await host.click("#killcam-btn");
    await host.waitForSelector("#killcam:not(.hidden)");
    const k0 = await host.evaluate(() => replayer.i);
    await host.waitForTimeout(600);
    const k1 = await host.evaluate(() => ({ i: replayer.i, active: replayer.active, results: !document.querySelector("#results").classList.contains("hidden") }));
    check(k1.active && k1.i > k0 && !k1.results, `the killcam plays (${k0} -> ${k1.i} ticks)`);
    await shot(host, "killcam");
    await host.click("#killcam");
    await host.waitForSelector("#results:not(.hidden)");
    check(!(await host.evaluate(() => replayer.active)), "and can be skipped back to the results");

    // Everyone votes for a rematch
    await host.click("#vote");
    await guest.waitForFunction(() => /1\/2/.test(document.querySelector("#vote").textContent));
    // The guest votes with the controller's A button. (Gamepads are read
    // each animation frame, which only runs in the tab in front.)
    await guest.bringToFront();
    await guest.evaluate(() => {
      const buttons = Array.from({ length: 17 }, (_, i) => ({ pressed: i === 0, value: i === 0 ? 1 : 0 }));
      window.__pads = [{ id: "Test pad", buttons, axes: [0, 0, 0, 0] }];
    });
    await guest.waitForFunction(() => bonkDebug.app.lobby.votes.length === 2 || bonkDebug.app.match && !bonkDebug.app.results);
    await guest.evaluate(() => { window.__pads = []; });
    await host.waitForSelector("#results.hidden", { state: "attached" });
    await host.waitForFunction(() => bonkDebug.app.match && !bonkDebug.app.results);
    check(true, "a rematch starts once everyone votes (the guest with a controller)");
    await host.waitForTimeout(500);
    const items = (await (await fetch(base + "/api/playtest")).json()).items;
    const reports = items.filter((i) => i.event === "playtest");
    // (The guest reloaded mid-match, so theirs may cover only a moment)
    const ann = reports.find((r) => r.name === "Ann");
    const full = ann && ann.ping.n > 0 && ann.states.n > 20 && ann.frames.fps > 0 && ann.device.ua;
    if (!full || reports.length !== 2) console.log(JSON.stringify(reports));
    check(reports.length === 2 && full && reports.every((r) => r.states.n > 0 && r.device.ua),
      `each player's report reaches the server (${reports.length}: ping, states, frame rate, device)`);
    check(items.some((i) => i.event === "client_error" && i.message === "e2e test error"), "browser errors reach the server too");
    await guest.keyboard.down("ArrowRight");  // (into the wall again, to end the rematch)
    await host.waitForSelector("#results:not(.hidden)", { timeout: 120000 });
    await guest.keyboard.up("ArrowRight");
    await host.click("#to-lobby");
    await host.waitForSelector("#lobby:not(.hidden)");
    await guest.waitForSelector("#lobby:not(.hidden)");
    check(true, "back to the lobby together");

    // Teams: the guest sees the sides and switches
    await host.click("#open-game-settings");
    await host.selectOption("#mode", "teams");
    await host.click("#game-settings-done");
    await guest.waitForFunction(() => document.querySelectorAll("#seats .team-head").length === 2);
    check(await guest.isVisible("#switch-team"), "teams show up in the lobby, with a switch button");
    const before = await guest.evaluate(() => bonkDebug.app.lobby.seats.find((s) => s.name === "Bob").team);
    await guest.click("#switch-team");
    await host.waitForFunction((t) => bonkDebug.app.lobby.seats.find((s) => s.name === "Bob").team === 1 - t, before);
    check(true, "switching team shows up for everyone");
    await host.click("#open-game-settings");
    await host.selectOption("#mode", "crown");
    await guest.waitForFunction(() => document.querySelector("#goal-label").textContent.startsWith("Hold"));
    await guest.click("#open-game-settings");
    check(await guest.isHidden("#round-time-box") && await guest.isDisabled("#mode"),
      "the goal and settings follow the mode (and the guest can look, not change)");
    await guest.click("#game-settings-done");
    await host.selectOption("#gravity", "low");
    await guest.waitForFunction(() => document.querySelector("#gravity").value === "low");
    check(true, "gravity reaches the guest");
    check((await guest.inputValue("#speed")) === "normal", "rooms start at the normal (slower) speed");
    await host.selectOption("#speed", "fast");
    await guest.waitForFunction(() => document.querySelector("#speed").value === "fast");
    await host.selectOption("#speed", "normal");
    check(true, "game speed reaches the guest");
    await host.check("#power-ups");
    await guest.waitForFunction(() => document.querySelector("#power-ups").checked);
    check(await guest.isDisabled("#power-ups"), "power-ups can be turned on (by the host only)");
    const allKinds = await host.$$eval("#power-kinds button", (b) => b.length);
    check(allKinds >= 10 && (await host.$$eval("#power-kinds button[aria-pressed=true]", (b) => b.length)) === allKinds,
      "every power-up can turn up to start with, the supers too");
    await host.click("#power-kinds [data-kind=punch]");
    await guest.waitForFunction(() => document.querySelector("#power-kinds [data-kind=punch]").getAttribute("aria-pressed") === "false");
    check(await guest.isDisabled("#power-kinds [data-kind=plane]") && (await guest.textContent("#sum-rest")).includes("Power-ups ⚡"),
      "the host picks which power-ups turn up, and the guest sees which");
    await host.click("#power-kinds [data-kind=punch]");
    await host.waitForFunction((n) => bonkDebug.app.lobby.settings.power_kinds.length === n, allKinds);
    await host.click("#game-settings-done");
    await shot(host, "lobby-crown");

    // A phone joins by searching for the code
    const phone = await open("phone", { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    await phone.goto(base + "/");
    await phone.fill("#name", "Cat");
    await phone.click("#find");
    check(!(await phone.$("#browse-code")), "the game list has one search box, no separate code box");
    await phone.fill("#browse-search", code.toLowerCase());
    await phone.waitForFunction(() => document.querySelectorAll("#games-list .game-row").length === 1);
    check(true, "searching a code finds its game");
    // (Ann and Bob have been pinging the server: their room shows it)
    await phone.waitForFunction(() => /^\d+ ms$/.test(document.querySelector("#games-list .ping-val").textContent), null, { timeout: 8000 });
    check(true, "the game list shows the players' ping");
    await shot(phone, "phone-browse");
    await phone.press("#browse-search", "Enter");
    await phone.waitForSelector("#pw-dialog:not(.hidden)");
    check(true, "joining by code asks for the password");
    await phone.fill("#pw-input", "wrong1");
    await phone.click("#pw-form button[type=submit]");
    await phone.waitForSelector("#pw-wrong:not(.hidden)");
    check(await phone.isVisible("#pw-dialog"), "a wrong password says so");
    await phone.fill("#pw-input", password);
    await phone.click("#pw-form button[type=submit]");
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
    await lost.click("#find");
    await lost.fill("#browse-search", "ZZZZ");
    await lost.press("#browse-search", "Enter");
    await lost.waitForSelector("#toast:not(.hidden)");
    check((await lost.textContent("#toast")).includes("doesn't exist"), "a bad code says so");

    // The server restarts for an update: open tabs are told, reconnect to the
    // new server and get their room back, with the same host and settings
    const settings = await host.evaluate(() => bonkDebug.app.lobby.settings);
    restarting = true;
    const exited = new Promise((r) => server.once("exit", r));
    server.kill("SIGTERM");
    await host.waitForFunction(() => /restarting/.test(document.querySelector("#status").textContent));
    check(true, "open tabs are told the server is restarting");
    check((await exited) === 0 || server.exitCode === 0, "the server shuts down cleanly");
    server = startServer();
    await waitForServer(base, server);
    await host.waitForFunction(() => document.querySelector("#status").classList.contains("hidden"), null, { timeout: 30000 });
    await guest.waitForFunction(() => document.querySelectorAll("#seats .seat").length >= 2, null, { timeout: 30000 });
    await host.waitForFunction(() => bonkDebug.app.lobby.seats.filter((x) => x.kind === "human").length === 2);
    // (The host's tab puts the settings back just after it's in: wait for them)
    await host.waitForFunction((want) => JSON.stringify(bonkDebug.app.lobby.settings) === want,
      JSON.stringify(settings), { timeout: 10000 }).catch(() => {});
    const after = await host.evaluate(() => bonkDebug.app.lobby);
    check(after.room === code && after.host === (await host.evaluate(() => bonkDebug.app.welcome.you)), "after a restart the room comes back, with the same host");
    check(JSON.stringify(after.settings) === JSON.stringify(settings), "and the same settings");
    restarting = false;

    // A tab from before a deploy is told to load the new version (once)
    const reloaded = guest.waitForEvent("load");
    await guest.evaluate(() => onMessage({ type: "error", message: "The game has been updated.", fatal: true, refresh: true }));
    await reloaded;
    await guest.waitForSelector("#lobby:not(.hidden)");
    check(true, "an out-of-date tab reloads itself");
    await guest.evaluate(() => onMessage({ type: "error", message: "The game has been updated.", fatal: true, refresh: true }));
    await guest.waitForTimeout(1000);
    check((await guest.textContent("#status")).includes("updated"), "but asks instead of reloading again and again");

    // Testing on a pretend slow network (netsim.js)
    const slow = await open("slow");
    await slow.goto(url + "&net=far&seed=1");
    check((await slow.textContent("#netsim")).includes("Simulating far"), "a simulated network says so on screen");
    await slow.fill("#name", "Eve");
    await slow.click("#join-form button");
    await slow.waitForSelector("#lobby:not(.hidden)");
    await slow.waitForFunction(() => bonkDebug.net.rtt > 170, null, { timeout: 10000 });
    check(true, `and its ping shows the delay (${Math.round(await slow.evaluate(() => bonkDebug.net.rtt))} ms)`);

    // Your stats: both matches are in the host's history
    const prof = await host.evaluate(() => profileStore.get());
    check(prof.stats.matches === 2 && prof.history.length === 2 && prof.history[0].map === "classic" && prof.history[0].of === prof.history[0].players,
      `matches go into your history (${prof.stats.matches}: ${prof.history.map((h) => h.mode + " " + h.place + "/" + h.of).join(", ")})`);
    await host.goto(base + "/");
    await host.click("#open-profile");
    await host.click("#me-tabs [data-tab=stats]");
    check((await host.$$eval("#stats .stat-history li", (els) => els.length)) === 2 && (await host.isVisible(".stat-tiles")),
      "the stats screen shows your totals and recent matches");
    await shot(host, "stats");
    check(await host.isHidden("#download-data"), "guests have no data download (their profile is in the browser)");
    const fresh = await open("fresh");
    await fresh.goto(base + "/");
    await fresh.click("#open-profile");
    await fresh.click("#me-tabs [data-tab=stats]");
    check((await fresh.textContent("#stats-body")).includes("No matches yet"), "a new browser has no matches");

    await fresh.click("#me-done");
    check(!(await fresh.$("#replay-file")) && !(await fresh.$("#replay-download")), "there are no replay files to watch or download");
    check((await fetch(base + "/api/replay", { method: "POST", body: "{}" })).status === 404, "and no server routes for them");

    // A public game (#35): made from the game browser, with bots, and
    // started. Someone else sees it listed, joins while it's on and takes
    // over a bot's seat
    const q1 = await open("quick1");
    await q1.goto(base + "/");
    await q1.fill("#name", "Quinn");
    await q1.click("#find");
    await q1.waitForSelector("#browse:not(.hidden)");
    check(q1.url().endsWith("/play"), "Find a game opens the game browser at /play");
    await shot(q1, "browse-empty");
    check(!(await q1.$("#quick")) && !(await q1.$("#empty-quick")), "there are no play-with-bots buttons: you make a public or private game");
    await q1.click("#new-game");
    await q1.click('#new-privacy [data-private="0"]');
    await q1.click("#new-create");
    await q1.waitForSelector("#lobby:not(.hidden)");
    check(/\/r\/[A-Z]{4}$/.test(q1.url()) && await q1.isVisible('#privacy [data-private="0"].on'), "a public game has no password");
    await q1.click("#open-game-settings");
    await q1.selectOption("#mode", "knockouts");
    await q1.click("#game-settings-done");
    await q1.waitForFunction(() => app.lobby.settings.mode === "knockouts");
    await q1.click("#add-bot");
    await q1.waitForFunction(() => document.querySelectorAll("#seats .seat").length === 3);
    check(await q1.isVisible("#map-preview") && await q1.isVisible("#seats .open-seat"), "the lobby shows the map and the open seats");
    await shot(q1, "lobby-public");
    await q1.click("#start");
    await q1.waitForSelector("#game:not(.hidden)", { timeout: 8000 });
    const q2 = await open("quick2");
    await q2.goto(base + "/");
    await q2.fill("#name", "sh1thead");
    await q2.click("#find");
    await q2.waitForSelector("#games-list .game-row");
    await q2.check("#hide-locked");
    await q2.waitForFunction(() => !document.querySelector("#games-list .game-row.locked"));
    check(true, "Hide private games hides the private ones");
    const listed = await q2.textContent("#games-list");
    check(listed.includes("Knockouts") && listed.includes("Floating Platform") && listed.includes("Playing"),
      "the browser lists the public game: its mode, map and that it's on");
    await shot(q2, "browse");
    await q2.selectOption("#filter-map", "platform");
    check((await q2.$$("#games-list .game-row")).length === 1, "and filters by map");
    check(await q2.evaluate(() => document.querySelectorAll("#filter-map option").length === Object.keys(NAMES.maps).length + 1 &&
      document.querySelectorAll("#filter-mode option").length === Object.keys(NAMES.modes).length + 1),
    "the map and mode filters offer every map and mode, played right now or not");
    check(!(await q2.$(".browse-bar .seg")), "there's no All / Open seats / In lobby switch");
    await q2.fill("#browse-search", "nothing like this");
    await q2.waitForSelector("#games-empty:not(.hidden)");
    check((await q2.textContent("#games-empty-text")).includes("match these filters"), "a search with no games says so");
    await q2.click("#clear-filters");
    await q2.waitForSelector("#games-list .game-row");
    await q2.click("#games-list .game-row:not(.locked) .g-join button");
    await q2.waitForSelector("#game:not(.hidden)");
    await q2.waitForFunction(() => app.match.slots.some((s) => s.id === me.id), null, { timeout: 5000 });
    check(true, "joining while a match is on takes over a bot's seat");
    const q2name = await q2.evaluate(() => app.match.slots.find((s) => s.id === me.id).name);
    check(/^Player \d\d$/.test(q2name), `an offensive name is replaced (${q2name})`);
    await q1.waitForFunction((n) => app.match.slots.some((s) => s.kind === "human" && s.name === n), q2name);
    check(!(await q1.evaluate(() => JSON.stringify(app.lobby).includes(me.token))), "nobody is sent anyone's token");
    // Mute them (from settings, during the match): their emotes and name go
    await q1.keyboard.press("Escape");
    await q1.click("#people-list .person-btn");
    await q1.check("#person-mute");
    await shot(q1, "person");
    await q1.selectOption("#report-reason", "name");
    await q1.click("#report-send");
    await q1.waitForFunction(() => /Thanks/.test(document.querySelector("#toast").textContent));
    await q1.click("#person-close");
    await q1.click("#me-done");
    check(await q1.evaluate(() => app.match.slots.some((s) => s.name === "Muted player")), "a muted player's name is hidden");
    await q2.keyboard.press("Digit1");
    await q2.waitForTimeout(500);
    check(await q1.evaluate(() => !bonkDebug.fx.emotes.some((e) => app.match.slots[e.slot].name === "Muted player")), "and their emotes");
    const playerReports = await (await fetch(base + "/api/reports")).json();
    check(playerReports.items.length === 1 && playerReports.items[0].reported.name === q2name && playerReports.items[0].reporter.name === "Quinn",
      "a report reaches the server");
    // Out of a match to the lobby (a bot plays for you), back in, and out for good
    await q2.click("#go-lobby");
    await q2.waitForSelector("#lobby:not(.hidden)");
    check(await q2.isVisible("#back-to-match"), "you can go to the lobby during a match, with a way back");
    const q2slot = await q2.evaluate(() => app.match.slots.findIndex((s) => s.id === me.id));
    await q1.waitForFunction((k) => (bonkDebug.app.last.stand_ins || []).includes(k), q2slot);
    check(true, "a bot plays for you while you're in the lobby");
    await shot(q2, "lobby-during-match");
    await q2.click("#back-to-match");
    await q2.waitForSelector("#game:not(.hidden)");
    await q1.waitForFunction((k) => !(bonkDebug.app.last.stand_ins || []).includes(k), q2slot);
    check(true, "and you can jump back into the match");
    await q2.click("#go-lobby");
    await q2.click("#leave");
    await q2.waitForSelector("#home:not(.hidden)");
    check(true, "and leave the room from there");
    // The host, now alone with bots, ends the match to change the map
    check(await q2.isHidden("#end-match"), "only the host can end a match");
    await q1.click("#end-match");
    await q1.waitForSelector("#lobby:not(.hidden)");
    check(await q1.isHidden("#results") && await q1.isEnabled("#start") &&
      (await q1.textContent("#chat-log")).includes("ended the match"), "the host can end a match early: back to the lobby, no results");
    await q1.close(); await q2.close();

    // Saved before profiles: the old settings come along
    const old = await open("old");
    await old.addInitScript(() => {
      if (localStorage.getItem("bonk.profile")) return;
      localStorage.setItem("bonk.name", "Olga"); localStorage.setItem("bonk.color", "4");
      localStorage.setItem("bonk.pattern", "dots"); localStorage.setItem("bonk.muted", "1");
      localStorage.setItem("bonk.prefs", JSON.stringify({ shake: false, keys: { heavy: "KeyJ" } }));
    });
    await old.goto(base + "/");
    const moved = await old.evaluate(() => ({ p: profileStore.get(), left: localStorage.getItem("bonk.name"), shake: prefs.shake, muted: sound.muted }));
    check(moved.p.name === "Olga" && moved.p.color === 4 && moved.p.pattern === "dots" && moved.muted && !moved.shake
      && moved.p.prefs.keys.heavy === "KeyJ" && moved.left === null && (await old.inputValue("#name")) === "Olga",
      "settings saved before profiles move into the profile");

    // The page's Content-Security-Policy blocks nothing the game uses: a
    // match against a bot with it on (no waitForFunction here: it needs eval)
    const strict = await open("strict", undefined, true);
    const violations = [];
    strict.on("console", (m) => { if (/Content Security Policy/i.test(m.text())) violations.push(m.text()); });
    await strict.goto(base + "/");
    check(/script-src 'self'/.test((await strict.evaluate(async () => (await fetch("/")).headers.get("content-security-policy"))) || ""),
      "the page is served with a Content-Security-Policy");
    await strict.fill("#name", "Cass");
    await strict.click("#find");
    await strict.waitForSelector("#browse:not(.hidden)");
    await strict.click("#new-game");
    await strict.click('#new-privacy [data-private="0"]');
    await strict.click("#new-create");
    await strict.waitForSelector("#lobby:not(.hidden)");
    await strict.click("#add-bot");
    await strict.waitForSelector("#seats .seat >> nth=1");
    await strict.click("#start");
    await strict.waitForSelector("#game:not(.hidden)", { timeout: 8000 });
    await strict.keyboard.down("ArrowLeft");
    await strict.waitForTimeout(1500);
    await strict.keyboard.up("ArrowLeft");
    check(await strict.evaluate(() => bonkDebug.app.states.length > 0 && bonkDebug.net.rtt !== null),
      "with the Content-Security-Policy on, the game connects, plays and gets states");
    check(violations.length === 0, "the policy blocks nothing" + (violations.length ? ": " + violations.join(" | ") : ""));

    // With a ping, the balls near yours are drawn predicted, at the same
    // moment as yours (js/net.js otherPositions); unticking it in Settings,
    // or ?predict_others=0, draws them where the server last had them
    const toLobby = async (page) => {
      await page.click("#find");
      await page.waitForSelector("#browse:not(.hidden)");
      await page.click("#new-game");
      await page.click("#new-create");
      await page.waitForSelector("#lobby:not(.hidden)");
      await page.evaluate(() => send({ type: "settings", map: "platform", mode: "knockouts", first_to: 50,
        bots: ["bot:hard", "bot:hard", "bot:hard"] }));
      await page.waitForFunction(() => document.querySelector("#map").value === "platform");
    };
    const startFromLobby = async (page) => {
      await page.evaluate(() => send({ type: "start" }));
      await page.waitForSelector("#game:not(.hidden)", { timeout: 8000 });
    };
    const startLagged = async (page) => { await toLobby(page); await startFromLobby(page); };
    // Settings, from the lobby's or the game's gear: flip the switch, close
    const flipSetting = async (page, gear) => {
      await page.click(gear);
      await page.waitForSelector("#settings:not(.hidden)");
      const was = await page.isChecked("#set-predict");
      await page.click("#set-predict");
      await page.click("#me-close");
      await page.waitForSelector("#settings", { state: "hidden" });
      return was;
    };
    // Every frame for a while: the most any other ball was drawn predicted
    // (from now on: what it was before doesn't count)
    const watchNearby = (page) => page.evaluate(() => new Promise((resolve) => {
      bonkDebug.near.w.length = 0;
      let most = 0, predicted = 0, frames = 0, btn = false, own = 0;
      const t0 = performance.now();
      const look = () => {
        const S = bonkDebug.app.states.length && bonkDebug.app.states[bonkDebug.app.states.length - 1][1];
        if (S && Array.isArray(S.btn)) btn = true;
        for (const w of bonkDebug.near.w) if (w > most) most = w;
        if (bonkDebug.near.at) predicted += 1;
        if (bonkDebug.own.base) own += 1;
        frames += 1;
        if (performance.now() - t0 < 9000 && most < 0.9) requestAnimationFrame(look);
        else resolve({ most, predicted, frames, btn, own: own > 0 });
      };
      requestAnimationFrame(look);
    }));
    const lagged = async (name, q = "") => {
      const page = await open(name);
      await page.goto(base + "/?lag=120&jitter=10&seed=1" + q);
      await page.fill("#name", "Pip");
      return page;
    };
    const onPage = await lagged("predict on");
    await startLagged(onPage);
    const on = await watchNearby(onPage);
    check(on.btn && on.predicted > 0 && on.most > 0.5,
      `with a ping, a ball near yours is drawn predicted (most ${on.most.toFixed(2)}, ${on.predicted}/${on.frames} frames)`);
    const off = await watchNearby(await (async () => { const p = await lagged("predict off", "&predict_others=0"); await startLagged(p); return p; })());
    check(off.btn && off.most === 0 && off.own, "?predict_others=0: the others are drawn as before, yours still predicted");

    // The setting (Settings: Show nearby balls where they are now): on to
    // start with; unticked, the others are drawn as before; ticked again
    // mid-match, predicted again straight away; and it's remembered
    const setPage = await lagged("predict setting");
    await toLobby(setPage);
    check(await flipSetting(setPage, "#open-settings-lobby"), "Settings: Show nearby balls where they are now, on to start with");
    await startFromLobby(setPage);
    const unticked = await watchNearby(setPage);
    check(unticked.btn && unticked.most === 0 && unticked.own, "unticked in Settings: the others are drawn as before, yours still predicted");
    check(!(await flipSetting(setPage, "#open-settings-game")), "it was unticked, and can be ticked again in the middle of a match");
    const ticked = await watchNearby(setPage);
    check(ticked.most > 0.5, `ticked again mid-match: nearby balls are predicted again straight away (most ${ticked.most.toFixed(2)})`);
    await flipSetting(setPage, "#open-settings-game");
    await setPage.reload();
    check(await setPage.evaluate(() => prefs.predictOthers === false && !predictOthers()), "unticked, it stays off after a reload");

    // Every ping in a match says how smoothly states come (js/net.js
    // stalls, for /admin): a steady connection has no stalls, one that
    // stalls (netsim: what a lost packet does to TCP) has some
    const pings = async (name, q) => {
      const page = await open(name);
      await page.goto(base + "/?" + q);
      await page.fill("#name", "Sal");
      await startLagged(page);
      await page.evaluate(() => {
        window.sentPings = [];
        const real = window.send;
        window.send = (msg) => { if (msg.type === "ping") window.sentPings.push(msg); return real(msg); };
      });
      await page.waitForTimeout(6500);
      return page.evaluate(() => window.sentPings);
    };
    const steady = await pings("pings steady", "lag=60&seed=2");
    const inMatch = steady.filter((m) => m.states > 0);
    // (about 30 a second; the first ping of a match gets part of a second, and
    // maybe no delay or round trip yet: it's only just started)
    const whole = inMatch.slice(1, -1);
    check(whole.length >= 3 && whole.every((m) => m.states >= 20 && m.states <= 40 && typeof m.delay === "number"
      && typeof m.rtt === "number") && inMatch.every((m) => Number.isInteger(m.stalls)),
      `in a match, each ping says the drawing delay and how many states came (${inMatch.map((m) => m.states).join(", ")})`);
    check(inMatch.reduce((a, m) => a + m.stalls, 0) === 0, "a steady connection: no stalls");
    const stalling = await pings("pings stalling", "lag=60&stall=400&stall_every=1.5&seed=2");
    const stalled = stalling.reduce((a, m) => a + (m.stalls || 0), 0);
    check(stalled > 0, `a connection that stalls: the pings count them (${stalled} in about 6 s)`);

    check(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch((e) => { console.error(e); process.exit(1); });
