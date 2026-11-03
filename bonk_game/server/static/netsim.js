// Pretend the network is worse than it is, for testing on one machine.
//
//   ?net=wifi | mobile | far | bad      a preset (PRESETS below)
//   ?lag=150        ms added to the round trip
//   ?jitter=40      ms of random extra round-trip delay, on average
//   ?stall=400      a stall: nothing arrives for this many ms, then it all
//   ?stall_every=10   comes at once (what a lost packet does to TCP), on
//                     average every this many seconds
//   ?seed=7         the same "random" network each time
//
// Messages keep their order, as they do over a WebSocket (TCP): a late one
// holds up the ones behind it. Each direction gets half the lag and jitter
// and its own stalls.
//
// Used by js/core.js in the browser and by tests in Node.
(function (root) {
  "use strict";

  const PRESETS = {
    wifi: { lag: 30, jitter: 15, stall: 150, stall_every: 30 },    // a decent home connection
    mobile: { lag: 80, jitter: 40, stall: 400, stall_every: 15 },  // a phone on 4G
    far: { lag: 180, jitter: 10, stall: 0, stall_every: 0 },       // another continent, wired
    bad: { lag: 150, jitter: 80, stall: 800, stall_every: 8 },     // weak signal
  };
  const KEYS = ["lag", "jitter", "stall", "stall_every"];

  // A small seeded random number generator (mulberry32)
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // The settings from a page's query string, or null for a normal network
  function fromParams(params) {
    const preset = PRESETS[params.get("net")] || null;
    const opts = { ...(preset || { lag: 0, jitter: 0, stall: 0, stall_every: 0 }) };
    let any = !!preset;
    for (const k of KEYS) {
      const v = params.get(k);
      if (v !== null && v !== "" && isFinite(+v)) { opts[k] = Math.max(0, +v); any = true; }
    }
    if (!any || KEYS.every((k) => !opts[k])) return null;
    if (!opts.stall_every) opts.stall = 0;
    opts.name = preset ? params.get("net") : "custom";
    opts.seed = isFinite(+params.get("seed")) && params.get("seed") ? +params.get("seed") : Date.now() % 1e9;
    return opts;
  }

  // One direction of the network: when a message sent at `now` arrives
  function link(opts, random) {
    const half = (opts.lag || 0) / 2;
    const jitter = (opts.jitter || 0) / 2;
    const every = (opts.stall_every || 0) * 1000;
    const stall = every ? opts.stall || 0 : 0;
    const expo = (mean) => -Math.log(1 - random()) * mean;
    let last = -Infinity;
    let stallAt = null;  // when the next stall starts
    return {
      arrival(now) {
        let at = now + half + (jitter ? Math.min(expo(jitter), jitter * 6) : 0);
        if (stall) {
          if (stallAt === null) stallAt = now + expo(every);
          while (stallAt + stall < now) stallAt += stall + expo(every);
          if (now >= stallAt) at = Math.max(at, stallAt + stall);
        }
        last = Math.max(last, at);  // in order, as over TCP
        return last;
      },
    };
  }

  // Both directions, for a page: .up and .down each run callbacks when their
  // message "arrives". setTimeout alone could run two in the wrong order.
  function make(opts) {
    const random = rng(opts.seed || 1);
    const pipe = (l) => {
      const queue = [];
      let timer = null;
      const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
      const run = () => {
        timer = null;
        const t = now();
        while (queue.length && queue[0][0] <= t + 0.5) queue.shift()[1]();
        if (queue.length) timer = setTimeout(run, queue[0][0] - t);
      };
      return (fn) => {
        queue.push([l.arrival(now()), fn]);
        if (timer === null) timer = setTimeout(run, Math.max(0, queue[0][0] - now()));
      };
    };
    return { opts, up: pipe(link(opts, random)), down: pipe(link(opts, random)) };
  }

  function describe(opts) {
    const parts = [`+${opts.lag} ms`];
    if (opts.jitter) parts.push(`±${opts.jitter}`);
    if (opts.stall) parts.push(`${opts.stall} ms stalls every ~${opts.stall_every} s`);
    return `${opts.name === "custom" ? "Simulated network" : "Simulating " + opts.name}: ${parts.join(", ")}`;
  }

  const api = { PRESETS, fromParams, link, make, rng, describe };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BonkNetSim = api;
})(typeof window !== "undefined" ? window : this);
