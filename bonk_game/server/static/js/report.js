// bonk web client: Playtest reports (see bonk_game/server/playtest.py).
// During a match this counts what you saw: ping, states that came late,
// how far your own ball had to be corrected (rubber-banding) and the frame
// rate. After the match it's sent to the server with how it felt, if you
// pick one on the results screen. JavaScript errors are sent as they
// happen. The server turns this off with BONK_PLAYTEST=0.
//
// Loaded first so it catches errors in the other files; everything it uses
// from them (app, send, $) is only touched later, while running.
"use strict";

const LATE_GAP = 100;   // ms between states: one was late (they come every 33)
const BIG_FIX = 6;      // px: a correction to your ball you'd notice
const HUGE_FIX = 20;    // px: a jump

const playtest = {
  on: false,            // the server wants reports (welcome.playtest)
  cur: null,            // this match's numbers
  pending: null,        // the last match's report, until it's sent
  reconnects: 0,
  errors: [],           // waiting to be sent
  errorsSent: 0,

  start(watching) {
    this.flush();
    if (!this.on) return;
    this.cur = { began: performance.now(), watching, pings: [], lastState: null, states: 0, late: 0,
                 maxGap: 0, missed: 0, fixes: 0, big: 0, huge: 0, maxFix: 0, sumFix: 0,
                 frames: 0, frameTime: 0, slow: 0, frozen: 0, guessed: 0, delay: 0, delays: 0, reconnects: this.reconnects };
  },
  ping(ms) { if (this.cur) this.cur.pings.push(ms); },
  state(ok) {
    const c = this.cur;
    if (!c) return;
    if (!ok) { c.missed++; return; }
    const now = performance.now();
    if (c.lastState !== null) {
      const gap = now - c.lastState;
      if (gap > LATE_GAP) c.late++;
      c.maxGap = Math.max(c.maxGap, gap);
    }
    c.lastState = now;
    c.states++;
  },
  correction(px) {
    const c = this.cur;
    if (!c) return;
    c.fixes++; c.sumFix += px; c.maxFix = Math.max(c.maxFix, px);
    if (px > BIG_FIX) c.big++;
    if (px > HUGE_FIX) c.huge++;
  },
  // frozen: the next state was so late that everything stood still for
  // that frame; guessed: it was late, so the frame carried on along the
  // way things were moving (draw.js); delay: how far behind the match was
  // drawn (clock.js)
  frame(ms, frozen, guessed, delay) {
    const c = this.cur;
    if (!c || document.hidden) return;
    c.frames++; c.frameTime += ms;
    if (ms > 50) c.slow++;
    if (frozen) c.frozen++;
    if (guessed) c.guessed++;
    if (delay !== null && delay !== undefined) { c.delay += delay; c.delays++; }
  },
  reconnect() { this.reconnects++; },

  // The match is over: hold its report until you say how it felt (or move on)
  finish() {
    const c = this.cur;
    this.cur = null;
    if (!c) return;
    const p = c.pings.slice().sort((a, b) => a - b);
    const q = (f) => (p.length ? p[Math.min(p.length - 1, Math.floor(p.length * f))] : null);
    let jitter = 0;
    for (let k = 1; k < c.pings.length; k++) jitter += Math.abs(c.pings[k] - c.pings[k - 1]);
    const conn = navigator.connection || {};
    this.pending = {
      type: "report",
      seconds: (performance.now() - c.began) / 1000,
      watching: c.watching, predict: PREDICT, lag: NET_SIM ? NET_SIM.lag : 0,
      sim: NET_SIM ? BonkNetSim.describe(NET_SIM) : "",
      reconnects: this.reconnects - c.reconnects,
      ping: { n: p.length, min: p[0] ?? null, med: q(0.5), p95: q(0.95), max: p[p.length - 1] ?? null,
              jitter: c.pings.length > 1 ? jitter / (c.pings.length - 1) : null },
      states: { n: c.states, late: c.late, max_gap: c.maxGap, missed: c.missed },
      corrections: { n: c.fixes, big: c.big, huge: c.huge, max: c.maxFix, avg: c.fixes ? c.sumFix / c.fixes : 0 },
      frames: { fps: c.frameTime ? (c.frames * 1000) / c.frameTime : null, slow: c.slow,
                frozen: c.frames ? (100 * c.frozen) / c.frames : 0,
                guessed: c.frames ? (100 * c.guessed) / c.frames : 0,
                delay: c.delays ? c.delay / c.delays : null },
      device: { ua: navigator.userAgent, screen: `${screen.width}x${screen.height}`,
                net: conn.effectiveType || "", touch: "ontouchstart" in window || navigator.maxTouchPoints > 0,
                pad: [...(navigator.getGamepads ? navigator.getGamepads() : [])].some(Boolean) },
    };
    this.showFeel();
  },
  // Send the last match's report, with how it felt if you said
  flush() {
    $("feel-note").blur();  // (so the next match's keys aren't typed into it)
    const r = this.pending;
    this.pending = null;
    if (!r || !app.ws || app.ws.readyState !== WebSocket.OPEN) return;
    const picked = document.querySelector("#feel button.picked");
    if (picked) r.feel = picked.dataset.feel;
    const note = $("feel-note").value.trim();
    if (note) r.note = note.slice(0, 500);
    send(r);
  },

  showFeel() {
    for (const b of document.querySelectorAll("#feel button")) b.classList.remove("picked");
    $("feel-note").value = "";
    $("feel-thanks").classList.add("hidden");
    $("feel").classList.toggle("hidden", !this.pending || this.pending.watching);
  },

  error(message, where) {
    if (this.errorsSent + this.errors.length >= 5) return;
    this.errors.push({ type: "client_error", message: String(message).slice(0, 300), where: String(where || "").slice(0, 120) });
    this.sendErrors();
  },
  sendErrors() {
    if (!this.on || typeof app === "undefined" || !app.ws || app.ws.readyState !== WebSocket.OPEN) return;
    while (this.errors.length) { send(this.errors.shift()); this.errorsSent++; }
  },
};

window.addEventListener("error", (e) => {
  const file = (e.filename || "").split("/").pop().split("?")[0];
  playtest.error(e.message || "error", file ? `${file}:${e.lineno}:${e.colno}` : "");
});
window.addEventListener("unhandledrejection", (e) => {
  const r = e.reason;
  playtest.error("unhandled promise: " + (r && r.message ? r.message : String(r)), "");
});
// Closing the tab on the results screen: send what we have
window.addEventListener("pagehide", () => { try { playtest.flush(); } catch (e) { /* closing anyway */ } });

// "How did that match feel?" on the results screen
for (const b of document.querySelectorAll("#feel button")) {
  b.addEventListener("click", () => {
    for (const o of document.querySelectorAll("#feel button")) o.classList.toggle("picked", o === b && !o.classList.contains("picked"));
    $("feel-thanks").classList.toggle("hidden", !document.querySelector("#feel button.picked"));
  });
}
