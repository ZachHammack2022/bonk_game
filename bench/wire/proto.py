"""A prototype binary format for state messages, for the wire benchmark
only (bench/wire/bench.py). Not used by the game.

It's the "hot part binary, the rest JSON" design: the fields in nearly
every message are packed; anything else rides along as a small JSON tail,
so the message means exactly what the JSON one did (delta.py's format),
and static/delta.js can apply it unchanged.

    u8   version (1)
    u8   flags   1 keyframe ("state", else "d")   2 has t       4 has timer
                 8 has players   16 players is a whole list (else changes)
                 32 has a JSON tail
    u32  tick
    u32  t * 100                              (if has t)
    i16  timer * 10                           (if has timer)
    u8   count, then per ball: u8 slot, i16 x*10, i16 y*10,
         u8 heavy*100 | 128 if alive          (if has players)
    u16  length, then that many bytes of JSON (if has tail)
    i16 vx*10, i16 vy*10, u8 standing         (only in the message to a
                                               player: their own ball, "you")

Positions and speeds are already rounded to 0.1 (scene.py) and heavy to
0.01, so packing them loses nothing; positions past +-3276.7 px (a ball
flying far off the map) are clamped, which is the one change: decode()
says how many it clamped.
"""
import json
import struct

VERSION = 1
KEY, HAS_T, HAS_TIMER, HAS_PLAYERS, PLAYERS_LIST, HAS_TAIL = 1, 2, 4, 8, 16, 32
HOT = ("type", "tick", "t", "timer", "players")
LIM = 32767

_HEAD = struct.Struct("<BBI")
_U32 = struct.Struct("<I")
_I16 = struct.Struct("<h")
_U16 = struct.Struct("<H")
_YOU = struct.Struct("<hhB")
_BALLS = {}  # count -> Struct for that many balls


def _balls(n):
    s = _BALLS.get(n)
    if s is None:
        s = _BALLS[n] = struct.Struct("<B" + "BhhB" * n)
    return s


def _q(v):
    q = round(v * 10)
    return LIM if q > LIM else -LIM if q < -LIM else q


def encode(msg):
    """A "state" or "d" message (a dict) as bytes, without "you"."""
    flags = KEY if msg["type"] == "state" else 0
    parts = []
    t = msg.get("t")
    if t is not None:
        flags |= HAS_T
        parts.append(_U32.pack(round(t * 100)))
    timer = msg.get("timer")
    timer_hot = isinstance(timer, (int, float)) and not isinstance(timer, bool)
    if timer_hot:
        flags |= HAS_TIMER
        parts.append(_I16.pack(_q(timer)))
    players = msg.get("players")
    if players is not None:
        flags |= HAS_PLAYERS
        if isinstance(players, list):
            flags |= PLAYERS_LIST
            items = enumerate(players)
        else:
            items = ((int(k), v) for k, v in players.items())
        vals = []
        for i, (x, y, heavy, alive) in items:
            vals += (i, _q(x), _q(y), round(heavy * 100) | (128 if alive else 0))
        n = len(vals) // 4
        parts.append(_balls(n).pack(n, *vals))
    rest = {k: v for k, v in msg.items() if k not in HOT}
    if "timer" in msg and not timer_hot:
        rest["timer"] = timer
    for k in ("t", "players"):
        if k in msg and msg[k] is None:
            rest[k] = None
    if rest:
        flags |= HAS_TAIL
        tail = json.dumps(rest, separators=(",", ":")).encode()
        parts.append(_U16.pack(len(tail)))
        parts.append(tail)
    return _HEAD.pack(VERSION, flags, msg["tick"]) + b"".join(parts)


def you(motion):
    """The bytes to add for one player's own ball: (vx, vy, standing)."""
    vx, vy, ground = motion
    return _YOU.pack(_q(vx), _q(vy), ground)


def _num(q, scale):
    v = q / scale
    return int(v) if v == int(v) else v


def decode(data):
    """bytes -> (the message as a dict, as JSON would have given it; how
    many numbers were clamped)."""
    version, flags, tick = _HEAD.unpack_from(data, 0)
    if version != VERSION:
        raise ValueError(f"unknown version {version}")
    o = _HEAD.size
    msg = {"type": "state" if flags & KEY else "d", "tick": tick}
    clamped = 0
    if flags & HAS_T:
        msg["t"] = _num(_U32.unpack_from(data, o)[0], 100)
        o += 4
    if flags & HAS_TIMER:
        msg["timer"] = _num(_I16.unpack_from(data, o)[0], 10)
        o += 2
    if flags & HAS_PLAYERS:
        n = data[o]
        vals = _balls(n).unpack_from(data, o)[1:]
        o += _balls(n).size
        balls = []
        for k in range(n):
            i, x, y, h = vals[4 * k: 4 * k + 4]
            clamped += (abs(x) == LIM) + (abs(y) == LIM)
            balls.append((i, [_num(x, 10), _num(y, 10), _num(h & 127, 100), 1 if h & 128 else 0]))
        msg["players"] = [b for _, b in balls] if flags & PLAYERS_LIST else {str(i): b for i, b in balls}
    if flags & HAS_TAIL:
        (n,) = _U16.unpack_from(data, o)
        o += 2
        msg.update(json.loads(data[o:o + n]))
        o += n
    if len(data) - o == _YOU.size:
        vx, vy, ground = _YOU.unpack_from(data, o)
        clamped += (abs(vx) == LIM) + (abs(vy) == LIM)
        msg["you"] = [_num(vx, 10), _num(vy, 10), ground]
        o += _YOU.size
    if o != len(data):
        raise ValueError(f"{len(data) - o} bytes left over")
    return msg, clamped
