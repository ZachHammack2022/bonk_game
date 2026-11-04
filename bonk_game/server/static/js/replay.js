// bonk web client: Replays and the killcam (see bonk_game/server/replay.py).
//
// - Killcam: the browser keeps the last few seconds of the match it was
//   sent; on the results screen 🎬 plays the final knockout in slow motion.
// - ⬇ Replay downloads the whole match as a small file (everyone's inputs).
// - 🎞 Watch a replay (home screen): the server plays a file back through
//   the same physics and sends the states; you can pause, change speed and
//   jump around.
//
// Both feed states into app.states as if they were arriving from a match,
// so the match is drawn exactly as usual (draw.js).
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
    if (!$("replay-bar").classList.contains("hidden")) updateReplayBar();
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

// On the results screen: what can be watched
function showReplayButtons(msg) {
  $("killcam-btn").classList.toggle("hidden", !killcamClip());
  $("replay-download").classList.toggle("hidden", !msg.replay);
}
$("replay-download").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = `/api/rooms/${app.room}/replay`;
  a.download = "";
  a.click();
});

// ---------------------------------------------------------------------------
// Watching a replay file
// ---------------------------------------------------------------------------
$("open-replay").addEventListener("click", () => $("replay-file").click());
$("replay-file").addEventListener("change", async () => {
  const f = $("replay-file").files[0];
  $("replay-file").value = "";
  if (!f) return;
  status("Loading the replay…");
  let body;
  try {
    const r = await fetch("/api/replay", { method: "POST", body: await f.text(), headers: { "Content-Type": "application/json" } });
    body = await r.json();
    if (!r.ok) throw new Error(body.error || "Couldn't play that replay.");
  } catch (e) {
    status("");
    toast(e.message || "Couldn't play that replay.", true);
    return;
  }
  status("");
  watchReplay(body);
});

function watchReplay(body) {
  // Rebuild every tick's full state from the changes (delta.js)
  const states = [];
  let last = null;
  for (const m of body.states) {
    last = m.type === "state" ? m : BonkDelta.apply(last, m);
    if (last) states.push(last);
  }
  app.match = body.match;
  applyLooks(app.match);
  app.results = null;
  app.room = null;
  $("results").classList.add("hidden");
  $("emotes").classList.add("hidden");
  $("replay-bar").classList.remove("hidden");
  $("go-lobby").classList.add("hidden");  // (no room: Done goes home)
  $("replay-seek").max = String(states.length - 1);
  show("game");
  resize();
  if (!body.engine) toast("This replay was made by another version of the game, so it may not play out the same.");
  replayer.start(states, { onEnd: () => updateReplayBar() });
}

function leaveReplay() {
  replayer.stop();
  $("replay-bar").classList.add("hidden");
  app.match = null;
  show("home");
}

const fmtTime = (ms) => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
function updateReplayBar() {
  const n = replayer.states.length;
  const want = replayer.playing ? "pause" : "play";
  if ($("replay-play").dataset.icon !== want) {
    $("replay-play").innerHTML = icon(want);
    $("replay-play").dataset.icon = want;
  }
  if (document.activeElement !== $("replay-seek")) $("replay-seek").value = String(Math.min(replayer.i, n - 1));
  $("replay-time").textContent = `${fmtTime(Math.min(replayer.clock, n * TICK_MS))} / ${fmtTime(n * TICK_MS)}`;
}
$("replay-play").addEventListener("click", () => {
  if (!replayer.playing && replayer.i >= replayer.states.length) replayer.seek(0);
  replayer.playing = !replayer.playing;
  replayer.last = performance.now();
  updateReplayBar();
});
$("replay-speed").addEventListener("change", () => { replayer.speed = +$("replay-speed").value; });
$("replay-seek").addEventListener("input", () => { fx.reset(); replayer.seek(+$("replay-seek").value); updateReplayBar(); });
$("replay-back").addEventListener("click", leaveReplay);
