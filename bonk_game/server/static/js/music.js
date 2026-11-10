// bonk web client: Music, made live with Web Audio like the sound effects
// (no audio files): a looping track for each screen and map, and short
// stings for big moments.
//   - Home, the game list, the leaderboard and the lobby: Cozy Lobby
//   - A match: its map's track (MAP_TRACKS); when the timer runs out
//     (overtime or sudden death): Sudden Death
//   - The results: a victory sting, then Oom-Pah Parade
// Its own volume (Settings: prefs.music) under the main one; M mutes it
// with everything else. It pauses while the tab is hidden.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

const music = (() => {
  let ctx = null, bus = null, stingBus = null, noiseBuf = null;
  let out = null;          // where the instrument being played goes (a track's gain, or the stings')
  let current = null;      // { track, gain, step, next, timer }
  let wanted = null;       // the track id the screen wants (played once sound is unlocked)

  // --- the instruments --------------------------------------------------------
  const mtof = (m) => 440 * Math.pow(2, (m - 69) / 12);
  const NOTE = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  function midi(name) {
    const m = /^([A-G])([#b]?)(-?\d)$/.exec(name);
    return m ? 12 * (+m[3] + 1) + NOTE[m[1]] + (m[2] === "#" ? 1 : m[2] === "b" ? -1 : 0) : null;
  }
  // "E5 . G5 ." (16 to a bar) -> [[step, midi], ...]
  const bars = (list) => list.flatMap((s, b) => s.trim().split(/\s+/)
    .map((t, i) => [b * 16 + i, t === "." ? null : midi(t)]).filter((x) => x[1] !== null));
  const chords = (cs, steps, len) => cs.flatMap((c, b) => steps.flatMap((s) => c.map((m) => [b * 16 + s, m, len])));

  function env(g, t, a, peak, decay) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + a);
    g.gain.exponentialRampToValueAtTime(0.0001, t + a + decay);
  }
  function osc(type, f, t, end, to, detune = 0) {
    const o = ctx.createOscillator();
    o.type = type; o.frequency.setValueAtTime(f, t); o.detune.value = detune;
    o.connect(to); o.start(t); o.stop(end);
    return o;
  }
  function gain(to = out) { const g = ctx.createGain(); g.connect(to); return g; }
  function lfo(rate, depth, param, t, end) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = rate; g.gain.value = depth; o.connect(g); g.connect(param); o.start(t); o.stop(end);
  }
  function filter(type, freq, q, to) {
    const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q; f.connect(to); return f;
  }
  const I = {
    marimba(t, m, d, v) {
      const g = gain(); env(g, t, 0.003, 0.32 * v, 0.45); osc("sine", mtof(m), t, t + 0.6, g);
      const h = gain(); env(h, t, 0.002, 0.08 * v, 0.08); osc("sine", mtof(m) * 3.99, t, t + 0.15, h);
    },
    glock(t, m, d, v) {
      [[1, 0.2, 0.9], [2.76, 0.06, 0.3], [5.4, 0.03, 0.12]].forEach(([k, a, dec]) => {
        const g = gain(); env(g, t, 0.002, a * v, dec); osc("sine", mtof(m) * k, t, t + dec + 0.1, g);
      });
    },
    pluck(t, m, d, v) {
      const g = gain(); env(g, t, 0.004, 0.38 * v, 0.32);
      const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.connect(g);
      lp.frequency.setValueAtTime(1400, t); lp.frequency.exponentialRampToValueAtTime(220, t + 0.3);
      osc("triangle", mtof(m), t, t + 0.4, lp); osc("sawtooth", mtof(m), t, t + 0.4, lp, 6);
    },
    square(t, m, d, v) {
      const g = gain(); env(g, t, 0.004, 0.085 * v, Math.max(0.08, d * 0.9));
      const o = osc("square", mtof(m), t, t + d + 0.05, g); lfo(6, 9, o.detune, t + 0.08, t + d + 0.05);
    },
    arp(t, m, d, v) { const g = gain(); env(g, t, 0.002, 0.035 * v, 0.07); osc("square", mtof(m), t, t + 0.1, g); },
    tri(t, m, d, v) { const g = gain(); env(g, t, 0.004, 0.3 * v, Math.max(0.1, d * 0.85)); osc("triangle", mtof(m), t, t + d + 0.05, g); },
    ep(t, m, d, v) {
      const g = gain();
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.11 * v, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.05 * v, t + 0.3); g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.6);
      const trem = gain(g); lfo(4.5, 0.25, trem.gain, t, t + d + 0.7);
      osc("sine", mtof(m), t, t + d + 0.7, trem); osc("sine", mtof(m) * 2, t, t + d + 0.7, trem, 3);
      const bell = gain(g); env(bell, t, 0.002, 0.3, 0.15); osc("sine", mtof(m) * 7, t, t + 0.2, bell);
    },
    steel(t, m, d, v) {
      [[1, 0.24, 0.7], [2, 0.12, 0.45], [3, 0.05, 0.25], [4.2, 0.03, 0.12]].forEach(([k, a, dec]) => {
        const g = gain(); env(g, t, 0.004, a * v, dec); osc("sine", mtof(m) * k, t, t + dec + 0.1, g, k === 1 ? 4 : 0);
      });
    },
    tuba(t, m, d, v) {
      const g = gain(); env(g, t, 0.03, 0.32 * v, Math.max(0.15, d * 0.8));
      osc("sawtooth", mtof(m), t, t + d + 0.1, filter("lowpass", 380, 2, g));
    },
    stab(t, m, d, v) {
      const g = gain(); env(g, t, 0.008, 0.06 * v, 0.13); const lp = filter("lowpass", 1800, 1, g);
      osc("sawtooth", mtof(m), t, t + 0.2, lp); osc("sawtooth", mtof(m), t, t + 0.2, lp, 9);
    },
    kazoo(t, m, d, v) {
      const g = gain(); env(g, t, 0.03, 0.12 * v, Math.max(0.1, d * 0.85));
      const bp = filter("bandpass", 1100, 3, g);
      const o = osc("sawtooth", mtof(m), t, t + d + 0.1, bp);
      o.frequency.setValueAtTime(mtof(m) * 0.94, t); o.frequency.exponentialRampToValueAtTime(mtof(m), t + 0.06);
      lfo(6.5, 22, o.detune, t, t + d + 0.1);
    },
    saw(t, m, d, v) {
      const g = gain(); env(g, t, 0.003, 0.16 * v, 0.16);
      const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.Q.value = 6; lp.connect(g);
      lp.frequency.setValueAtTime(2400, t); lp.frequency.exponentialRampToValueAtTime(300, t + 0.14);
      osc("sawtooth", mtof(m), t, t + 0.2, lp);
    },
    pad(t, m, d, v) {
      const g = gain();
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.035 * v, t + 0.3);
      g.gain.setValueAtTime(0.035 * v, t + d - 0.2); g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.3);
      const lp = filter("lowpass", 1200, 1, g);
      osc("sawtooth", mtof(m), t, t + d + 0.4, lp, -8); osc("sawtooth", mtof(m), t, t + d + 0.4, lp, 8);
    },
    boing(t, m, d, v) {
      const g = gain(); env(g, t, 0.005, 0.18 * v, 0.35);
      const o = osc("sine", mtof(m), t, t + 0.4, g);
      o.frequency.exponentialRampToValueAtTime(mtof(m + 12), t + 0.12);
      o.frequency.exponentialRampToValueAtTime(mtof(m + 7), t + 0.35);
    },
  };
  function noise(t, dur, type, freq, peak, q = 1) {
    const s = ctx.createBufferSource(); s.buffer = noiseBuf;
    const g = gain(); env(g, t, 0.001, peak, dur);
    s.connect(filter(type, freq, q, g)); s.start(t, Math.random() * 0.5); s.stop(t + dur + 0.05);
  }
  const D = {
    kick(t, v) { const g = gain(); env(g, t, 0.002, 0.9 * v, 0.22); osc("sine", 150, t, t + 0.3, g).frequency.exponentialRampToValueAtTime(45, t + 0.13); },
    snare(t, v) { noise(t, 0.14, "bandpass", 1900, 0.35 * v, 0.8); const g = gain(); env(g, t, 0.002, 0.18 * v, 0.07); osc("triangle", 190, t, t + 0.1, g); },
    clap(t, v) { for (const k of [0, 0.011, 0.023]) noise(t + k, 0.07 + k, "bandpass", 1300, 0.22 * v, 1.2); },
    hat(t, v) { noise(t, 0.035, "highpass", 7500, 0.12 * v); },
    shaker(t, v) { noise(t, 0.05, "bandpass", 6000, 0.07 * v, 0.7); },
    rim(t, v) { const g = gain(); env(g, t, 0.001, 0.14 * v, 0.03); osc("square", 1700, t, t + 0.05, g); },
    wood(t, v) { const g = gain(); env(g, t, 0.001, 0.22 * v, 0.05); osc("sine", 1250, t, t + 0.08, g); },
    crash(t, v) { noise(t, 1.1, "highpass", 5000, 0.12 * v); },
    crackle(t) { if (Math.random() < 0.35) noise(t + Math.random() * 0.05, 0.004, "highpass", 3000, 0.04 + Math.random() * 0.05); },
  };

  // --- the tracks: 4 bars of 16th-note steps -----------------------------------
  // parts: [instrument, [[step, midi, (length)]], length in steps, velocity]
  // drums: {drum: [steps in every bar]}
  const TRACKS = {
    lobby: {
      title: "Cozy Lobby", bpm: 82, swing: 0.18, soft: 0.7,
      parts: [
        ["ep", chords([[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59, 62]], [0], 9)
          .concat(chords([[57, 60, 64], [55, 59, 62], [53, 57, 60], [52, 55, 59]], [10], 5)), 1, 0.8],
        ["ep", bars(["A5 . . . . . G5 . . . E5 . . . . .", "D5 . . . E5 . . . G5 . . . . . . .",
          "F5 . . . E5 . D5 . . . C5 . . . . .", "E5 . . . . . . . D5 . . . . . . ."]), 4, 0.7],
        ["tri", bars(["F2 . . . . . . . . . C3 . . . . .", "E2 . . . . . . . . . B2 . . . . .",
          "D2 . . . . . . . . . A2 . . . . .", "C2 . . . . . . . . . G2 . . . E2 ."]), 4, 0.8],
      ],
      drums: { kick: [0, 7, 10], rim: [4, 12], hat: [0, 2, 4, 6, 8, 10, 12, 14], crackle: [...Array(16).keys()] },
    },
    bounce: {
      title: "Squishy Bounce", bpm: 124,
      parts: [
        ["marimba", bars(["E5 . G5 . C6 . G5 . E5 . D5 . C5 . . .", "A4 . C5 . E5 . A5 . G5 . E5 . C5 . . .",
          "F5 . A5 . C6 . A5 . G5 . F5 . E5 . D5 .", "D5 . G5 . B5 . D6 . B5 . G5 . . . . ."]), 2],
        ["pluck", bars(["C3 . . . . . C3 . G2 . . C3 . . C4 .", "A2 . . . . . A2 . E2 . . A2 . . A3 .",
          "F2 . . . . . F2 . C3 . . F2 . . F3 .", "G2 . . . . . G2 . D3 . . G2 . . G3 ."]), 2],
        ["boing", [[62, midi("G4")]], 4],
      ],
      drums: { kick: [0, 8, 10], clap: [4, 12], hat: [2, 6, 10, 14], shaker: [1, 3, 5, 7, 9, 11, 13, 15] },
    },
    island: {
      title: "Island Hop", bpm: 112,
      parts: [
        ["steel", bars(["C5 . . A4 . . C5 . F5 . . E5 . . C5 .", "D5 . . F5 . . D5 . Bb4 . . D5 . . F5 .",
          "E5 . . G5 . . E5 . C5 . . E5 . . G5 .", "F5 . . E5 . . C5 . A4 . . . . . . ."]), 3],
        ["steel", chords([[65, 69], [62, 65], [64, 67], [65, 69]], [6, 14], 2), 2, 0.45],
        ["pluck", bars(["F2 . . . . . C3 . F3 . . . C3 . . .", "Bb1 . . . . . F2 . Bb2 . . . F2 . . .",
          "C2 . . . . . G2 . C3 . . . G2 . . .", "F2 . . . . . C3 . F3 . . . C3 . . ."]), 2, 0.9],
      ],
      drums: { kick: [0, 8], wood: [0, 3, 6, 10, 12], shaker: [...Array(16).keys()], rim: [4, 12] },
    },
    arcade: {
      title: "Pocket Arcade", bpm: 140,
      parts: [
        ["square", bars(["A5 . . . E5 . A5 . B5 . C6 . B5 . A5 .", "C6 . . . A5 . F5 . G5 . A5 . . . . .",
          "G5 . . . E5 . G5 . C6 . D6 . E6 . D6 .", "B5 . . . G5 . D5 . G5 . A5 . B5 . . ."]), 2],
        ["arp", [[57, 60, 64], [53, 57, 60], [60, 64, 67], [55, 59, 62]].flatMap((c, b) =>
          Array.from({ length: 16 }, (_, i) => [b * 16 + i, c[i % 3] + (i % 6 >= 3 ? 12 : 0)])), 1],
        ["tri", bars(["A2 . A3 . A2 . A3 . A2 . A3 . A2 . A3 .", "F2 . F3 . F2 . F3 . F2 . F3 . F2 . F3 .",
          "C3 . C4 . C3 . C4 . C3 . C4 . C3 . C4 .", "G2 . G3 . G2 . G3 . G2 . G3 . B2 . D3 ."]), 2, 0.8],
      ],
      drums: { kick: [0, 8], snare: [4, 12], hat: [0, 2, 4, 6, 8, 10, 12, 14] },
    },
    // New: a music box for the toy-box Sliding Platform
    toybox: {
      title: "Toy Box", bpm: 116,
      parts: [
        ["glock", bars(["B5 . D6 . G6 . D6 . B5 . . . A5 . G5 .", "E5 . G5 . B5 . G5 . E5 . . . F#5 . G5 .",
          "E5 . G5 . C6 . E6 . D6 . C6 . B5 . A5 .", "F#5 . A5 . D6 . A5 . F#5 . . . D5 . . ."]), 3],
        ["marimba", chords([[67, 71], [64, 67], [64, 72], [66, 69]], [4, 12], 2), 2, 0.4],
        ["pluck", bars(["G2 . . . D3 . . . G2 . . . D3 . . .", "E2 . . . B2 . . . E2 . . . B2 . . .",
          "C3 . . . G2 . . . C3 . . . G2 . . .", "D2 . . . A2 . . . D3 . . . F#2 . . ."]), 2, 0.8],
      ],
      drums: { kick: [0, 8], rim: [4, 12], shaker: [0, 2, 4, 6, 8, 10, 12, 14] },
    },
    // New: a funky slap bass for the ramps and decks
    rumble: {
      title: "Ramp Rumble", bpm: 104,
      parts: [
        ["saw", bars(["E2 . . E3 . . E2 . G2 . A2 . . B2 . D3", "E2 . . E3 . . E2 . D3 . B2 . A2 . G2 .",
          "A2 . . A3 . . A2 . C3 . D3 . . E3 . G3", "B2 . . B3 . . B2 . D#3 . F#3 . A3 . B3 ."]), 1, 1.1],
        ["stab", chords([[62, 64, 67], [62, 64, 67], [61, 64, 67], [63, 66, 69]], [2, 6, 11, 14], 1), 1, 1.2],
        ["square", bars([". . . . . . . . . . . . . . . .", ". . . . . . . . . . . . . . . .",
          ". . . . . . . . . . . . . . . .", "B5 . A5 . F#5 . E5 . D#5 . . . B4 . . ."]), 1, 0.8],
      ],
      drums: { kick: [0, 3, 10], clap: [4, 12], hat: [...Array(16).keys()] },
    },
    sudden: {
      title: "Sudden Death", bpm: 152,
      parts: [
        ["square", bars(["D5 . D5 . F5 . . A5 . . G5 . F5 . E5 .", "D5 . D5 . F5 . . Bb5 . . A5 . G5 . F5 .",
          "E5 . E5 . G5 . . C6 . . Bb5 . A5 . G5 .", "A5 . . . C#6 . . . E6 . . . C#6 . A5 ."]), 1.6, 0.9],
        ["saw", [38, 34, 36, 33].flatMap((r, b) => Array.from({ length: 8 }, (_, i) => [b * 16 + i * 2, r + (i % 4 === 3 ? 12 : 0)])), 1],
        ["pad", chords([[62, 65, 69], [58, 62, 65], [60, 64, 67], [57, 61, 64]], [0], 16), 16],
      ],
      drums: { kick: [0, 4, 8, 12], snare: [4, 12], hat: [1, 3, 5, 7, 9, 11, 13, 15], wood: [0, 4, 8, 12] },
    },
    parade: {
      title: "Oom-Pah Parade", bpm: 108, crashOnLoop: true,
      parts: [
        ["kazoo", bars(["G4 . . . C5 . . . E5 . D5 . C5 . . .", "B4 . . . D5 . . . G5 . F5 . D5 . . .",
          "E5 . . . G5 . . . C6 . B5 . A5 . G5 .", "F5 . . . D5 . . . B4 . G4 . C5 . . ."]), 2],
        ["tuba", bars(["C2 . . . . . . . G1 . . . . . . .", "G1 . . . . . . . D2 . . . . . . .",
          "C2 . . . . . . . G1 . . . . . . .", "G1 . . . . . . . B1 . . . C2 . . ."]), 3],
        ["stab", chords([[60, 64, 67], [59, 62, 67], [60, 64, 67], [59, 62, 65]], [4, 12], 1), 1],
      ],
      drums: { kick: [0, 8], snare: [4, 12, 14, 15] },
    },
  };
  // Each map's match music (one not listed gets Squishy Bounce)
  const MAP_TRACKS = { classic: "arcade", platform: "bounce", slider: "toybox", swing: "island",
                       decks: "rumble", grand: "bounce", ramps: "rumble" };

  // --- volume ---------------------------------------------------------------------
  const MUSIC_LEVEL = 0.45;  // (next to the sound effects, at the same settings)
  const musicVolume = () => (sound.muted ? 0 : prefs.volume * (prefs.music ?? 0.5) * MUSIC_LEVEL);
  const stingVolume = () => (sound.muted ? 0 : prefs.volume * 0.6);

  function setup() {
    if (ctx) return true;
    sound.unlock();
    if (!sound.ctx) return false;
    ctx = sound.ctx;
    bus = ctx.createGain(); bus.gain.value = musicVolume(); bus.connect(ctx.destination);
    stingBus = ctx.createGain(); stingBus.gain.value = stingVolume(); stingBus.connect(ctx.destination);
    noiseBuf = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    return true;
  }

  // --- playing ----------------------------------------------------------------------
  const AHEAD = 0.15;
  function tick() {
    const c = current;
    if (!c) return;
    const tr = c.track, dt = 60 / tr.bpm / 4, soft = tr.soft || 1;
    while (c.next < ctx.currentTime + AHEAD) {
      const s = c.step % 64, inBar = s % 16;
      const t = c.next + (tr.swing && inBar % 4 === 2 ? tr.swing * dt * 2 : 0);
      out = c.gain;
      for (const [inst, notes, len, vel = 1] of tr.parts) {
        for (const n of notes) if (n[0] === s) I[inst](t, n[1], (n[2] || len) * dt, vel * soft);
      }
      for (const [name, steps] of Object.entries(tr.drums)) if (steps.includes(inBar)) D[name](t, soft);
      if (tr.crashOnLoop && s === 0) D.crash(t, soft);
      c.step += 1;
      c.next += dt;
    }
  }
  // Changing tracks isn't a hard cut: the old one eases down, and once it's
  // nearly gone the new one eases up from silence (slower than it went down)
  const FADE_OUT = 1.5, FADE_IN = 2.5;
  // A smooth S-curve from the gain's level now to `to`, over secs
  function ease(param, to, t, secs) {
    const from = param.value, n = 32, curve = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const k = i / (n - 1);
      curve[i] = from + (to - from) * k * k * (3 - 2 * k);
    }
    if (param.cancelAndHoldAtTime) param.cancelAndHoldAtTime(t);
    else { param.cancelScheduledValues(t); param.setValueAtTime(from, t); }
    param.setValueCurveAtTime(curve, t, secs);
  }
  function fadeOut(c, secs = FADE_OUT) {
    clearInterval(c.timer);
    ease(c.gain.gain, 0, ctx.currentTime, secs);
    setTimeout(() => c.gain.disconnect(), (secs + 1) * 1000);
  }
  function start(id, delay = 0) {
    let gap = 0;
    if (current) { fadeOut(current); current = null; gap = FADE_OUT * 0.8; }
    if (!id || !TRACKS[id] || document.hidden || !setup()) return;
    const g = ctx.createGain(); g.connect(bus);
    g.gain.value = 0;
    const t = ctx.currentTime + 0.05 + Math.max(delay, gap);
    g.gain.setValueAtTime(0, t);
    g.gain.setValueCurveAtTime(Float32Array.from({ length: 32 }, (_, i) => { const k = i / 31; return k * k * (3 - 2 * k); }), t, FADE_IN);
    current = { id, track: TRACKS[id], gain: g, step: 0, next: t, full: t + FADE_IN };
    current.timer = setInterval(tick, 50);
    tick();
  }

  // --- what the game calls --------------------------------------------------------------
  const api = {
    TRACKS, MAP_TRACKS,
    get playing() { return current ? current.id : null; },
    // The track this screen wants (null: none). Starts it once sound is unlocked
    want(id, delay = 0) {
      if (id === wanted && (current ? current.id === id : !ctx)) return;
      wanted = id;
      if (ctx && ctx.state === "running") start(id, delay);
    },
    forMap(map) { return MAP_TRACKS[map] || "bounce"; },
    // Sound came on (a first click or key): play what's wanted
    unlocked() { if (setup() && wanted && !current) start(wanted); },
    volume() {
      if (!ctx) return;
      bus.gain.setTargetAtTime(musicVolume(), ctx.currentTime, 0.05);
      stingBus.gain.setTargetAtTime(stingVolume(), ctx.currentTime, 0.05);
    },
    // The music dips for a moment (a knockout, a super power), so the bonk is heard
    duck(depth = 0.35, secs = 0.7) {
      if (!ctx || !current || ctx.currentTime < current.full) return;  // (not while it's fading in)
      const t = ctx.currentTime, p = current.gain.gain;
      p.cancelScheduledValues(t); p.setValueAtTime(p.value, t);
      p.linearRampToValueAtTime(depth, t + 0.04); p.linearRampToValueAtTime(1, t + secs);
    },
    // A short sound over the music: "win", "ko", "sudden", "super"
    sting(name) {
      if (!setup() || sound.muted) return;
      out = stingBus;
      const t = ctx.currentTime + 0.02;
      if (name === "win") {
        [["C5", 0], ["E5", 0.12], ["G5", 0.24], ["C6", 0.36]].forEach(([n, k]) => I.marimba(t + k, midi(n), 0.2, 1.1));
        [60, 64, 67, 72].forEach((m) => I.ep(t + 0.5, m, 1.2, 1.2));
        D.crash(t + 0.5, 1);
      } else if (name === "ko") {
        const g = gain(); env(g, t, 0.003, 0.22, 0.4);
        osc("square", 880, t, t + 0.45, g).frequency.exponentialRampToValueAtTime(110, t + 0.4);
        D.kick(t, 1); D.clap(t + 0.02, 0.8);
      } else if (name === "sudden") {
        for (let k = 0; k < 3; k++) { D.wood(t + k * 0.18, 1.3); I.square(t + k * 0.18, midi("A5"), 0.1, 1); }
        I.square(t + 0.54, midi("D6"), 0.5, 1); D.crash(t + 0.54, 1);
      } else if (name === "super") {
        for (let k = 0; k < 8; k++) I.arp(t + k * 0.045, 72 + [0, 4, 7, 11, 12, 16, 19, 24][k], 0.08, 3);
        I.boing(t + 0.38, midi("C5"), 0.4, 1);
      }
    },
  };
  // Not while the tab is hidden; back to what's wanted when it shows again
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { if (current) { fadeOut(current, 0.2); current = null; } }
    else if (ctx && wanted) start(wanted);
  });
  for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, () => api.unlocked());
  wanted = $("game").classList.contains("hidden") ? "lobby" : null;  // (the page opens on a menu)
  return api;
})();
