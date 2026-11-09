"""Measure a bonk.io screen recording: where the ball, the floor, the seat's
planks and the rope are in every frame (recording.json is what this gave
for the Sinking Swing recording, November 2026).

    python -m bench.bonk_video.measure recording.mov [out.json]

Needs ffmpeg, numpy, Pillow and scipy (not part of the game's install). It
looks for the recording's colours: the pink ball, the green floor, the tan
planks and the faint rope line, at half the recording's size (947 px wide).
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage


def frame_masks(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    pink = (r > 200) & (g < 160) & (b > 130) & (b < 200)
    tan = (r > 160) & (r < 230) & (g > 130) & (g < 190) & (b > 80) & (b < 140) & (r - b > 60)
    green = (g > 160) & (r < 130) & (b > 120) & (b < 170)
    return pink, tan, green


def planks(tan):
    """[x, y, angle from vertical (degrees)] of each plank, left to right."""
    lab, n = ndimage.label(tan)
    out = []
    for k in range(1, n + 1):
        yy, xx = np.nonzero(lab == k)
        if len(xx) < 60:
            continue
        w, v = np.linalg.eigh(np.cov(np.vstack([xx, yy])))
        d = v[:, 1]
        ang = np.degrees(np.arctan2(d[0], d[1]))
        ang = (ang + 90) % 180 - 90
        out.append([float(xx.mean()), float(yy.mean()), float(ang)])
    return sorted(out)


def rope_angle(a, top_of_seat):
    """The rope's angle from straight down (degrees, + = seat to the right):
    a line fitted through the faint pixels above the seat."""
    s = a.sum(2)
    pts = []
    for y in range(5, int(top_of_seat), 3):
        row = s[y]
        xs = np.nonzero((row > np.median(row) + 45) & (row < 600))[0]
        xs = xs[(xs > 250) & (xs < 900)]
        if 0 < len(xs) < 6:
            pts.append((y, xs.mean()))
    if len(pts) < 10:
        return None
    pts = np.array(pts)
    slope = np.polyfit(pts[:, 0], pts[:, 1], 1)[0]
    return float(np.degrees(np.arctan(slope)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    video, out = argv[0], argv[1] if len(argv) > 1 else "recording.json"
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vf", "scale=947:-2", f"{tmp}/%05d.png"], check=True)
        rows = []
        for i, f in enumerate(sorted(glob.glob(os.path.join(tmp, "*.png")))):
            a = np.asarray(Image.open(f).convert("RGB")).astype(int)
            pink, tan, green = frame_masks(a)
            ys, xs = np.nonzero(pink)
            ball = [round(float(xs.mean()), 1), round(float(ys.mean()), 1),
                    round(float(np.sqrt(len(xs) / np.pi)), 1)] if len(xs) > 50 else None
            floor_rows = np.nonzero(green.sum(1) > 300)[0]
            pl = planks(tan)
            rope = rope_angle(a, min(p[1] for p in pl) - 45) if pl else None
            rows.append({"frame": i, "ball": ball, "floor": int(floor_rows.min()) if len(floor_rows) else None,
                         "planks": [[round(v, 1) for v in p] for p in pl],
                         "rope": None if rope is None else round(rope, 2)})
    json.dump({"fps": 60, "frames": rows}, open(out, "w"), separators=(",", ":"))
    print(f"{len(rows)} frames -> {out}")


if __name__ == "__main__":
    main()
