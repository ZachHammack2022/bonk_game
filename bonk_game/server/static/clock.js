// bonk web client: the playback clock, which says what moment of the match
// to draw.
//
// The browser draws the match a little in the past, blending between the
// two states either side of that moment, so motion stays smooth even though
// states only come 30 times a second. How far in the past is a trade-off:
//   - too little, and a state that comes late leaves nothing to blend
//     toward (everything stops for a moment: "frozen" in playtest reports);
//   - too much, and everything else in the match lags behind for nothing.
//
// So this measures how late states come and picks the delay to suit:
//   - Each state's tick says when the server made it. Arrival time minus
//     tick time is how long it took to get here (plus a constant: the two
//     clocks don't agree).
//   - We draw the moment by which 95 % of the last 10 s of states had
//     arrived, plus a tick (to have the next state to blend toward) and a
//     small margin. The odd stall (under 5 % of states) doesn't make every
//     match laggy; a connection that gets worse is caught within half a
//     second; one that gets better is trusted slowly, over 10 s.
//   - A steady connection draws ~40 ms behind; a jittery one gets what it
//     needs, up to 250 ms more than its quickest recent state.
//   - The clock runs slightly fast or slow (at most 6 %) to reach a new
//     delay, so the match never visibly jumps; it only jumps when far off
//     (a reconnect, a server that fell behind).
//   - It never runs more than GUESS_MS past the newest state: when states
//     stop coming (a stall), the match pauses and then catches up.
//
// When a state is later than even that, draw.js carries on for up to
// GUESS_MS along the way things were moving (extrapolating) rather than
// stopping; past that, it waits.
//
// Works in the browser (window.BonkClock) and in Node (tests/test_clock.py).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.BonkClock = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const WINDOW = 300;     // states remembered: 10 s (long enough that one stall is under 5 %)
  const RECENT = 30;      // the last second, for the quickest recent arrival
  const QUANTILE = 0.95;
  const MARGIN = 6;       // ms on top of the measured lateness and the tick
  const MAX_DELAY = 250;  // ms more than the quickest recent state, at most
  const MAX_SLEW = 0.06;  // run up to 6 % fast or slow to reach the delay wanted
  const SLEW_MS = 250;    // ...closing the gap over about this long
  const SNAP = 300;       // ms off: jump instead
  const GUESS_MS = 100;   // how far past the newest state draw.js may extrapolate

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function make(tickMs) {
    return {
      tickMs,
      offsets: [],    // arrival time minus tick time, for the last WINDOW states
      best: null,     // the quickest of those
      edge: null,     // the offset to draw at: match time = now - edge
      play: null,     // the match time being drawn, ms (tick * tickMs)
      newest: null,   // the newest tick that has arrived
      paused: false,  // waiting at the newest state (nothing new to draw)
      last: null,     // when tick() was last called

      // A state for `tick` arrived at `now` (ms, performance.now())
      arrive(tick, now) {
        this.offsets.push(now - tick * this.tickMs);
        this.newest = this.newest === null ? tick : Math.max(this.newest, tick);
        if (this.offsets.length > WINDOW) this.offsets.shift();
        const s = this.offsets.slice().sort((a, b) => a - b);
        this.best = s[0];
        const recent = Math.min(...this.offsets.slice(-RECENT));
        const q = s[Math.min(s.length - 1, Math.floor(s.length * QUANTILE))];
        this.edge = clamp(q, recent, recent + MAX_DELAY) + this.tickMs + MARGIN;
      },

      // The moment to draw at `now`, in ticks (fractional), or null before
      // any state has come
      tick(now) {
        if (this.edge === null) return null;
        const want = now - this.edge;
        if (this.play === null || Math.abs(want - this.play) > SNAP) {
          this.play = want;
        } else {
          const dt = Math.max(0, now - this.last);
          this.play += dt;
          this.play += dt * clamp((want - this.play) / SLEW_MS, -MAX_SLEW, MAX_SLEW);
        }
        // Never further past the newest state than draw.js will guess: if
        // states stop coming, the match pauses there (and catches up after)
        const most = this.newest * this.tickMs + GUESS_MS;
        this.paused = this.play >= most;
        this.play = Math.min(this.play, most);
        this.last = now;
        return this.play / this.tickMs;
      },

      // How far behind the quickest state of the last 10 s we're drawing, ms
      delay(now) {
        return this.play === null ? null : now - this.best - this.play;
      },

      reset() {
        this.offsets = []; this.best = this.edge = this.play = this.last = this.newest = null;
        this.paused = false;
      },
    };
  }

  return { make, WINDOW, QUANTILE, MARGIN, MAX_DELAY, MAX_SLEW, SNAP, GUESS_MS };
});
