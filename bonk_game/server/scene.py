"""Turn the game world into plain data the browser can draw.

Maps draw themselves by calling a Painter (bonk_game/ui/painter.py).
ShapeRecorder has the same methods, but instead of drawing it records a
list of shapes. That way a map's look is defined once and the web client
draws the same thing as the desktop game.

Shapes (all in world coordinates, 680 x 480, y down):
    {"t": "edges"}                                   red glow on deadly screen edges
                                                     ("s": 0: the bottom one only)
    {"t": "rect", "r": [x1, y1, x2, y2], "c": "#rrggbb", "k": kind}
    {"t": "poly", "p": [[x, y] x4], "l": lip, "c": ..., "k": kind}
                                                     rotated slab: its corners, and
                                                     the lip under its face (the
                                                     face is the slab minus the
                                                     lip at the bottom: the
                                                     client works it out)
    {"t": "ball", "x", "y", "r", "c", "k"}           round bumper
    {"t": "line", "a": [x, y], "b": [x, y], "c", "w"}
    {"t": "pivot", "x", "y"}                         the swing's pivot
    {"t": "rail", "x1", "x2", "y"}
    {"t": "spring", "a": [x, y], "b": [x, y], "c"}   a coil spring between two points
kind is "solid", "hazard", "pad", "wood" or "toy" (a painted toy block in
its own colour "c").
"""
from bonk_game.ui import theme


def hex_color(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c[:3])


def num(v, places=1):
    """A rounded number, written as short as JSON allows (12 not 12.0)."""
    r = round(float(v), places)
    return int(r) if r == int(r) else r


_r = num


def _pts(points):
    return [[_r(x), _r(y)] for x, y in points]


class ShapeRecorder:
    """Painter stand-in that records what a map draws."""

    def __init__(self):
        self.shapes = []

    def danger_edges(self, sides=True):
        self.shapes.append({"t": "edges"} if sides else {"t": "edges", "s": 0})

    def oriented_block(self, block, color, kind="solid"):
        self.shapes.append({"t": "poly", "p": _pts(block.corners()),
                            "l": _r(min(3, block.h / 3)), "c": hex_color(color), "k": kind})

    def bumper(self, x, y, r, color, kind="solid"):
        self.shapes.append({"t": "ball", "x": _r(x), "y": _r(y), "r": _r(r), "c": hex_color(color), "k": kind})

    def spring(self, x1, y1, x2, y2, color):
        self.shapes.append({"t": "spring", "a": [_r(x1), _r(y1)], "b": [_r(x2), _r(y2)], "c": hex_color(color)})

    def block(self, x1, y1, x2, y2, color, kind="solid"):
        self.shapes.append({"t": "rect", "r": [_r(x1), _r(y1), _r(x2), _r(y2)], "c": hex_color(color), "k": kind})

    def draw_block(self, block):
        # Same styling rules as Painter.draw_block
        kind = "hazard" if block.kill else "pad" if block.launch is not None else "solid"
        color = theme.HAZARD if block.kill else block.color
        if hasattr(block, "radius"):
            self.shapes.append({"t": "ball", "x": _r(block.cx), "y": _r(block.cy),
                                "r": _r(block.radius), "c": hex_color(color), "k": kind})
        elif hasattr(block, "angle"):
            self.shapes.append({"t": "poly", "p": _pts(block.corners()),
                                "l": _r(min(3, block.h / 3)), "c": hex_color(color), "k": kind})
        else:
            self.block(block.x1, block.y1, block.x2, block.y2, color, kind)

    def swing(self, swing):
        sx, sy = swing.seat_pos()
        self.shapes.append({"t": "line", "a": [_r(swing.px), _r(swing.py)], "b": [_r(sx), _r(sy)],
                            "c": hex_color(theme.ROPE), "w": 2.5})
        for plank in swing.planks():
            self.shapes.append({"t": "poly", "p": _pts(plank.corners()), "l": 3, "c": hex_color(theme.WOOD),
                                "k": "wood"})
        self.shapes.append({"t": "pivot", "x": _r(swing.px), "y": _r(swing.py)})

    def rail(self, x1, x2, y):
        self.shapes.append({"t": "rail", "x1": _r(x1), "x2": _r(x2), "y": _r(y)})


def level_shapes(game_map):
    """The shapes a map draws right now (moving parts included)."""
    rec = ShapeRecorder()
    game_map.render(rec)
    return rec.shapes


def player_state(p):
    """[x, y, how heavy 0-1, alive] for one player: what everyone sees.
    Positions to 0.1 px: finer than anyone can see."""
    heavy = 0.0
    if p.max_m > p.min_m:
        heavy = max(0.0, min(1.0, (p.m - p.min_m) / (p.max_m - p.min_m)))
    return [num(p.x), num(p.y), num(heavy, 2), 1 if p.alive else 0]


def player_motion(p):
    """[x speed, y speed, standing on something]: only for the player's own
    browser, which predicts its ball (physics.js). Speeds to 0.1 px a tick
    (the prediction's error from that is well under a pixel)."""
    return [num(p.x_v), num(p.y_v), 1 if p.grounded else 0]

