"""Our physics against the bonk.io recording (recording.json, made by
measure.py from a screen recording of the Sinking Swing rebuilt in bonk.io).

    python -m bench.bonk_video.compare

Prints gravity, how fast the floor sinks, and the swing coming back after a
ball lands in it, from the recording and from our game. Everything is in
our pixels (the recording's ball is 26 px across its radius, ours 20) and
real seconds at the default game speed.
"""
import json
import math
import os

import numpy as np

from bonk_game.envs.utils import stepping, world
from bonk_game.envs.utils.maps import make_map

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS_PER_SECOND = 30 * stepping.TIME_SCALE  # physics steps in a real second


def load():
    d = json.load(open(os.path.join(HERE, "recording.json")))
    return d, 20 / d["ball_radius"]  # (the recording's px -> ours)


def recorded_gravity(d, scale):
    """px/s^2, from the ball falling after the top of its flight into the
    seat (frames 338-366: not pressing up or down)."""
    frames = d["frames"][338:366]
    t = np.array([f["frame"] for f in frames]) / d["fps"]
    y = np.array([f["ball"][1] for f in frames]) * scale
    return 2 * np.polyfit(t, y, 2)[0]


def recorded_sink(d, scale):
    """px/s the floor sinks."""
    fl = [(f["frame"], f["floor"]) for f in d["frames"] if f["floor"] is not None]
    t = np.array([a for a, _ in fl]) / d["fps"]
    return np.polyfit(t, np.array([b for _, b in fl]) * scale, 1)[0]


def recorded_swing_back(d):
    """(seconds since the swing's furthest point, rope angle in degrees)
    from there to the end of the recording."""
    rope = [(f["frame"], f["rope"]) for f in d["frames"] if f["rope"] is not None]
    peak = max(rope, key=lambda r: r[1])[0]
    return [((k - peak) / d["fps"], a) for k, a in rope if k >= peak]


def our_swing_back(start_deg, seconds, swing=None):
    """Our swing let go at start_deg with a ball sitting in it: rope angle
    (degrees) every tick (30 a second) for `seconds`."""
    m = make_map("swing")
    if swing:
        for k, v in swing.items():
            setattr(m.swing, k, v)
    p, q = m.make_players()
    q.dies()
    m.steps = -10 ** 6  # (the floor stays put)
    m.swing.theta = math.radians(start_deg)
    sx, sy = m.swing.seat_pos()
    p.x, p.y, p.x_v, p.y_v = sx, sy + 15, 0, 0
    out = []
    for _ in range(int(seconds * 30) + 1):
        m.step(move=False)
        stepping.advance([p], m, time_scale=stepping.TIME_SCALE)
        out.append(math.degrees(m.swing.theta))
    return out


def swing_error(d=None, swing=None):
    """How far our swing coming back is from the recording's (rms degrees),
    and both, sampled every half second."""
    d = d or load()[0]
    rec = recorded_swing_back(d)
    t = np.array([a for a, _ in rec])
    ours = our_swing_back(rec[0][1], t[-1], swing)
    sim = np.interp(t, np.arange(1, len(ours) + 1) / 30, ours)
    theirs = np.array([b for _, b in rec])
    rms = float(np.sqrt(np.mean((sim - theirs) ** 2)))
    every = [(round(float(a), 1), round(float(b), 1), round(float(c), 1))
             for a, b, c in zip(t[::30], theirs[::30], sim[::30])]
    return rms, every


def main():
    d, scale = load()
    ours_g = world.GRAVITY * STEPS_PER_SECOND ** 2
    print(f"gravity: recording {recorded_gravity(d, scale):.0f} px/s^2, ours {ours_g:.0f}"
          f" (it was {world.TUNED_GRAVITY * STEPS_PER_SECOND ** 2:.0f})")
    m = make_map("swing")
    print(f"floor sinks: recording {recorded_sink(d, scale):.1f} px/s, ours {m.SINK_SPEED * STEPS_PER_SECOND:.1f}")
    rms, every = swing_error(d)
    print(f"swing coming back with a ball in it (rope angle, degrees): {rms:.2f} rms apart")
    print("| seconds | recording | ours |\n|---|---|---|")
    for t, a, b in every:
        print(f"| {t} | {a} | {b} |")


if __name__ == "__main__":
    main()
