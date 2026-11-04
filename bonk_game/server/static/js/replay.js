// bonk web client: the killcam.
//
// The browser keeps the last few seconds of the match it was sent; on the
// results screen Killcam plays the final knockout again in slow motion. It
// feeds those states into app.states as if they were arriving from the
// match, so it's drawn exactly as usual (draw.js).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

const KILLCAM_KEEP = 8 * 30;     // ticks of the match kept for the killcam
const KILLCAM_BEFORE = 3 * 30;   // ticks shown before the knockout
const KILLCAM_AFTER = 20;
const KILLCAM_SPEED = 0.4;

const replayer = {
  active: false,
  states: [],         // full states, one per tick
  i: 0,               // the next one to show
  clock: 0,           // ms of match time played
  speed: 1,
  playing: false,
  events: () => true, // which events to play (sounds, bursts, the feed)
  onEnd: null,
  last: 0,
  recent: [],         // the live match's last KILLCAM_KEEP states

  // The live match: keep its last few seconds
  keep(S) {
    if (this.active) return;
    this.recent.push(S);
    if (this.recent.length > KILLCAM_KEEP) this.recent.shift();
  },

  start(states, { speed = 1, events = () => true, onEnd = null, at = 0 } = {}) {
    Object.assign(this, { active: true, states, speed, events, onEnd, playing: true, last: performance.now() });
    own.tick = null; own.base = null;
    fx.reset();
    this.seek(at);
  },
  stop() {
    this.active = false;
    this.playing = false;
    app.states = [];
  },
  seek(k) {
    k = clamp(Math.round(k), 0, Math.max(0, this.states.length - 1));
    this.i = k;
    this.clock = k * TICK_MS;
    const S = this.states[Math.max(0, k - 1)];
    app.states = S ? [[performance.now(), S]] : [];
    app.last = S || null;
  },

  // The moment to draw (in ticks, like the live clock.js): a tick behind
  // the newest state shown, so there's always one to blend toward
  drawTick() {
    const first = this.states[0];
    return first ? first.tick + this.clock / TICK_MS - 1 : null;
  },

  // Each animation frame (draw.js), before drawing
  frame(now) {
    if (!this.active) return;
    const dt = Math.min(250, now - this.last);
    this.last = now;
    if (this.playing) this.clock += dt * this.speed;
    while (this.i < this.states.length && this.i * TICK_MS <= this.clock) {
      const S = this.states[this.i];
      app.states.push([now, S]);
      if (app.states.length > STATES_KEPT) app.states.shift();
      app.last = S;
      for (const ev of S.events || []) if (this.events(ev)) onEvent(ev, S);
      this.i++;
    }
    if (this.i >= this.states.length && this.playing && this.clock > this.states.length * TICK_MS + 500) {
      this.playing = false;
      if (this.onEnd) this.onEnd();
    }
  },
};

// ---------------------------------------------------------------------------
// Killcam
// ---------------------------------------------------------------------------
// The last knockout in what we kept (one by another player if there was one)
function killcamClip() {
  const R = replayer.recent;
  let at = -1, best = -1;
  for (let k = 0; k < R.length; k++) {
    for (const ev of R[k].events || []) {
      if (ev.e !== "death") continue;
      const score = ev.by !== null && ev.by !== undefined ? 2 : 1;
      if (score >= best) { best = score; at = k; }
    }
  }
  if (at < 0) return null;
  return { states: R.slice(Math.max(0, at - KILLCAM_BEFORE), at + KILLCAM_AFTER), ko: Math.min(at, KILLCAM_BEFORE) };
}

function playKillcam() {
  const clip = killcamClip();
  if (!clip) return;
  $("results").classList.add("hidden");
  $("killcam").classList.remove("hidden");
  replayer.start(clip.states, {
    speed: KILLCAM_SPEED,
    events: (ev) => ev.e === "death" || ev.e === "hit",
    onEnd: endKillcam,
  });
}
function endKillcam() {
  if (!$("killcam").classList.contains("hidden")) {
    replayer.stop();
    $("killcam").classList.add("hidden");
    if (app.results) $("results").classList.remove("hidden");
  }
}
$("killcam-btn").addEventListener("click", playKillcam);
$("killcam").addEventListener("click", endKillcam);

// On the results screen: the killcam, if there's a knockout to show
function showReplayButtons() {
  $("killcam-btn").classList.toggle("hidden", !killcamClip());
}
