"""Turn the game world into plain data the browser can draw.

Maps draw themselves by calling a Painter (bonk_game/ui/painter.py).
ShapeRecorder has the same methods, but instead of drawing it records a
list of shapes. That way a map's look is defined once and the web client
draws the same thing as the desktop game.

Shapes (all in world coordinates, 680 x 480, y down):
    {"t": "edges"}                                   red glow on deadly screen edges
    {"t": "rect", "r": [x1, y1, x2, y2], "c": "#rrggbb", "k": kind}
    {"t": "poly", "p": [[x, y] x4], "f": [[x, y] x4], "c": ..., "k": kind}
                                                     rotated slab: outline and face
    {"t": "ball", "x", "y", "r", "c", "k"}           round bumper
    {"t": "line", "a": [x, y], "b": [x, y], "c", "w"}
    {"t": "pivot", "x", "y"}                         the swing's pivot
    {"t": "rail", "x1", "x2", "y"}
kind is "solid", "hazard", "pad" or "wood".
"""
from bonk_game.ui import theme


def hex_color(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c[:3])


def _r(v):
    return round(float(v), 1)


def _pts(points):
    return [[_r(x), _r(y)] for x, y in points]


def oriented_face(block, lip):
    """Corners of an OrientedBlock's face: the block minus `lip` at the bottom.
    (Same as bonk_game.ui.painter.oriented_face, without needing pygame.)"""
    hw, hh = block.w / 2, block.h / 2
    pts = []
    for x, y in ((-hw, -hh), (hw, -hh), (hw, hh - lip), (-hw, hh - lip)):
        wx, wy = block.to_world(x, y)
        pts.append((block.cx + wx, block.cy + wy))
    return pts


class ShapeRecorder:
    """Painter stand-in that records what a map draws."""

    def __init__(self):
        self.shapes = []

    def danger_edges(self):
        self.shapes.append({"t": "edges"})

    def block(self, x1, y1, x2, y2, color, kind="solid"):
        self.shapes.append({"t": "rect", "r": [_r(x1), _r(y1), _r(x2), _r(y2)],
                            "c": hex_color(color), "k": kind})

    def draw_block(self, block):
        # Same styling rules as Painter.draw_block
        kind = "hazard" if block.kill else "pad" if block.launch is not None else "solid"
        color = theme.HAZARD if block.kill else block.color
        if hasattr(block, "radius"):
            self.shapes.append({"t": "ball", "x": _r(block.cx), "y": _r(block.cy),
                                "r": _r(block.radius), "c": hex_color(color), "k": kind})
        elif hasattr(block, "angle"):
            self.shapes.append({"t": "poly", "p": _pts(block.corners()),
                                "f": _pts(oriented_face(block, min(3, block.h / 3))),
                                "c": hex_color(color), "k": kind})
        else:
            self.block(block.x1, block.y1, block.x2, block.y2, color, kind)

    def swing(self, swing):
        sx, sy = swing.seat_pos()
        half = swing.seat_width / 2
        for end_x in (sx - half + 2, sx + half - 2):
            self.shapes.append({"t": "line", "a": [_r(swing.px), _r(swing.py)],
                                "b": [_r(end_x), _r(sy - swing.lip_height)],
                                "c": hex_color(theme.ROPE), "w": 2.5})
        for x1, y1, x2, y2 in swing.rects():
            self.block(x1, y1, x2, y2, theme.WOOD, "wood")
        self.shapes.append({"t": "pivot", "x": _r(swing.px), "y": _r(swing.py)})

    def rail(self, x1, x2, y):
        self.shapes.append({"t": "rail", "x1": _r(x1), "x2": _r(x2), "y": _r(y)})


def level_shapes(game_map):
    """The shapes a map draws right now (moving parts included)."""
    rec = ShapeRecorder()
    game_map.render(rec)
    return rec.shapes


def player_state(p):
    """[x, y, how heavy 0-1, alive] for one player."""
    heavy = 0.0
    if p.max_m > p.min_m:
        heavy = max(0.0, min(1.0, (p.m - p.min_m) / (p.max_m - p.min_m)))
    return [_r(p.x), _r(p.y), round(heavy, 2), 1 if p.alive else 0]
