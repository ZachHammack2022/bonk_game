// The browser side of bench/wire/proto.py (the prototype binary state
// format, for the wire benchmark only): an ArrayBuffer -> the same message
// object JSON.parse would have given. Works in Node and in a page.
(function (root) {
  "use strict";
  const KEY = 1, HAS_T = 2, HAS_TIMER = 4, HAS_PLAYERS = 8, PLAYERS_LIST = 16, HAS_TAIL = 32;
  const utf8 = new TextDecoder();

  function decode(buf) {
    const v = new DataView(buf);
    if (v.getUint8(0) !== 1) throw new Error("unknown version " + v.getUint8(0));
    const flags = v.getUint8(1);
    const msg = { type: flags & KEY ? "state" : "d", tick: v.getUint32(2, true) };
    let o = 6;
    if (flags & HAS_T) { msg.t = v.getUint32(o, true) / 100; o += 4; }
    if (flags & HAS_TIMER) { msg.timer = v.getInt16(o, true) / 10; o += 2; }
    if (flags & HAS_PLAYERS) {
      const n = v.getUint8(o); o += 1;
      const list = flags & PLAYERS_LIST;
      const players = list ? new Array(n) : {};
      for (let k = 0; k < n; k++) {
        const i = v.getUint8(o), h = v.getUint8(o + 5);
        const ball = [v.getInt16(o + 1, true) / 10, v.getInt16(o + 3, true) / 10, (h & 127) / 100, h & 128 ? 1 : 0];
        if (list) players[k] = ball; else players[i] = ball;
        o += 6;
      }
      msg.players = players;
    }
    if (flags & HAS_TAIL) {
      const n = v.getUint16(o, true); o += 2;
      Object.assign(msg, JSON.parse(utf8.decode(new Uint8Array(buf, o, n))));
      o += n;
    }
    if (buf.byteLength - o === 5) {
      msg.you = [v.getInt16(o, true) / 10, v.getInt16(o + 2, true) / 10, v.getUint8(o + 4)];
      o += 5;
    }
    if (o !== buf.byteLength) throw new Error(`${buf.byteLength - o} bytes left over`);
    return msg;
  }

  const api = { decode };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WireProto = api;
})(typeof window !== "undefined" ? window : this);
