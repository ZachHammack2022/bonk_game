"""Our physics against the bonk.io recording (recording.json, made by
measure.py from a screen recording of the Sinking Swing rebuilt in bonk.io).

    python -m bench.bonk_video.compare

Prints gravity, how fast the floor sinks and the swing's period, from the
recording and from our game, and how long a ride on our swing keeps going.
Everything is in our pixels (the recording's ball is 26 px across its
radius, ours 20) and real seconds at the default game speed.
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


def recorded_period(d):
    """The swing's period (s), from the recording: a quarter of a swing
    from the ball landing in the seat (the rope starts to move) to the
    furthest it went. (You were steering in the seat as well, so it's
    rough: within a few percent.)"""
    rope = [(f["frame"], f["rope"]) for f in d["frames"] if f["rope"] is not None]
    start = next(k for k, a in rope if a > 0.5)
    peak = max(rope, key=lambda r: r[1])[0]
    return 4 * (peak - start) / d["fps"]


def our_swing(start_deg, seconds, swing=None):
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


def our_period(angles):
    """The period (s) of a swing, from where it crosses the middle."""
    cross = [i / 30 for i, (a, b) in enumerate(zip(angles, angles[1:])) if a * b < 0]
    return 2 * (cross[-1] - cross[0]) / (len(cross) - 1)


def furthest(angles, t0, t1):
    """How far out it swung (degrees) between t0 and t1 seconds."""
    return max(abs(a) for a in angles[int(t0 * 30):int(t1 * 30)])


def main():
    d, scale = load()
    ours_g = world.GRAVITY * STEPS_PER_SECOND ** 2
    print(f"gravity: recording {recorded_gravity(d, scale):.0f} px/s^2, ours {ours_g:.0f}"
          f" (it was {world.TUNED_GRAVITY * STEPS_PER_SECOND ** 2:.0f})")
    m = make_map("swing")
    print(f"floor sinks: recording {recorded_sink(d, scale):.1f} px/s, ours {m.SINK_SPEED * STEPS_PER_SECOND:.1f}")
    swing = our_swing(20, 40)
    print(f"swing period: recording {recorded_period(d):.2f} s, ours {our_period(swing):.2f}")
    print("a ball riding it, let go at 20 degrees out: swinging "
          + ", ".join(f"{furthest(swing, t - 4, t):.0f} degrees out at {t} s" for t in (10, 20, 40)))


if __name__ == "__main__":
    main()
