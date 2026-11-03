"""Maps described by JSON files instead of Python classes.

Every *.json file in bonk_game/maps/ (shipped with the game), in ./maps/
(next to where you run the game), and in any folder listed in the
BONK_MAPS environment variable becomes a map. It shows up in the menu, in
main.py --train and as the gym env
bonk_game/bonk-<name>-v0.

Files that don't load are skipped with a message saying what's wrong.
Check a file with:

    python -m bonk_game.check_map path/to/map.json

The format is documented in the README ("Making maps") and by example in
bonk_game/maps/.
"""
import glob
import json
import math
import os
import re
import sys

import numpy as np

PACKAGE_MAPS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "maps")

COLORS = {
    "platform": "PLATFORM", "post": "POST", "pad": "PAD", "pit": "PIT",
    "wood": "WOOD", "hazard": "HAZARD", "rail": "RAIL",
}
PIECE_TYPES = ("block", "slope", "post", "bumper")
BODY_TYPES = ("swing", "slider")


class MapFileError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Validation helpers. Each takes the value and a "where" path for messages.
# ---------------------------------------------------------------------------
def _fail(where, msg):
    raise MapFileError(f"{where}: {msg}")


def _number(v, where, lo=None, hi=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        _fail(where, f"expected a number, got {json.dumps(v)}")
    if lo is not None and v < lo:
        _fail(where, f"must be at least {lo}, got {v}")
    if hi is not None and v > hi:
        _fail(where, f"must be at most {hi}, got {v}")
    return float(v)


def _numbers(v, n, where):
    if not isinstance(v, list) or len(v) != n:
        _fail(where, f"expected a list of {n} numbers, got {json.dumps(v)}")
    return [_number(x, f"{where}[{i}]") for i, x in enumerate(v)]


def _get(d, key, where, default=..., kind=None):
    if key not in d:
        if default is ...:
            _fail(where, f'missing "{key}"')
        return default
    v = d[key]
    if kind is not None and not isinstance(v, kind):
        names = kind.__name__ if isinstance(kind, type) else " or ".join(k.__name__ for k in kind)
        _fail(f"{where}.{key}", f"expected {names}, got {json.dumps(v)}")
    return v


def _check_keys(d, allowed, where):
    extra = sorted(set(d) - set(allowed))
    if extra:
        _fail(where, f"unknown key{'s' if len(extra) > 1 else ''} {', '.join(map(repr, extra))} "
                     f"(allowed: {', '.join(sorted(allowed))})")


def _color(v, where, default):
    from bonk_game.ui import theme
    if v is None:
        return getattr(theme, default)
    if isinstance(v, str):
        if v not in COLORS:
            _fail(where, f"unknown colour {v!r} (use one of {', '.join(COLORS)} or [r, g, b])")
        return getattr(theme, COLORS[v])
    rgb = _numbers(v, 3, where)
    if any(c < 0 or c > 255 for c in rgb):
        _fail(where, "colour values must be 0-255")
    return tuple(int(c) for c in rgb)


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------
_COMMON = {"type", "bounce", "friction", "launch", "kill", "color"}
_SHAPE_KEYS = {
    "block": {"rect"},
    "slope": {"center", "size", "angle"},
    "post": {"foot", "size", "lean"},
    "bumper": {"center", "radius"},
}


def _piece(spec, where):
    """Validate one piece; returns a function that builds a fresh copy."""
    from bonk_game.envs.utils.bodies import Block, Bumper, OrientedBlock

    if not isinstance(spec, dict):
        _fail(where, f"expected an object, got {json.dumps(spec)}")
    kind = _get(spec, "type", where, kind=str)
    if kind not in PIECE_TYPES:
        _fail(f"{where}.type", f"unknown piece type {kind!r} (use one of {', '.join(PIECE_TYPES)})")
    _check_keys(spec, _COMMON | _SHAPE_KEYS[kind], where)

    launch = spec.get("launch")
    kill = _get(spec, "kill", where, False, bool)
    opts = dict(
        restitution=_number(spec.get("bounce", 0.3), f"{where}.bounce", 0, 1.5),
        friction=_number(spec.get("friction", 0.04), f"{where}.friction", 0, 1),
        launch=None if launch is None else _number(launch, f"{where}.launch", 0, 40),
        kill=kill,
    )
    default_color = "HAZARD" if kill else "PAD" if launch is not None else "POST" if kind == "post" else "PLATFORM"
    color = _color(spec.get("color"), f"{where}.color", default_color)

    if kind == "block":
        x1, y1, x2, y2 = _numbers(_get(spec, "rect", where), 4, f"{where}.rect")
        if x2 <= x1 or y2 <= y1:
            _fail(f"{where}.rect", "should be [left, top, right, bottom] with right > left and bottom > top")
        return lambda: Block(x1, y1, x2, y2, color, **opts)
    if kind == "slope":
        cx, cy = _numbers(_get(spec, "center", where), 2, f"{where}.center")
        w, h = _numbers(_get(spec, "size", where), 2, f"{where}.size")
        angle = _number(_get(spec, "angle", where, 0), f"{where}.angle", -180, 180)
        _positive(w, h, f"{where}.size")
        return lambda: OrientedBlock(cx, cy, w, h, angle, color, **opts)
    if kind == "post":
        x, y = _numbers(_get(spec, "foot", where), 2, f"{where}.foot")
        w, h = _numbers(_get(spec, "size", where), 2, f"{where}.size")
        lean = _number(_get(spec, "lean", where, 0), f"{where}.lean", -90, 90)
        _positive(w, h, f"{where}.size")
        return lambda: OrientedBlock.standing(x, y, w, h, lean, color, **opts)
    cx, cy = _numbers(_get(spec, "center", where), 2, f"{where}.center")
    r = _number(_get(spec, "radius", where), f"{where}.radius", 1)
    return lambda: Bumper(cx, cy, r, color, **opts)


def _positive(w, h, where):
    if w <= 0 or h <= 0:
        _fail(where, "width and height must be positive")


def _body(spec, where):
    """Validate a swing or slider; returns a function that builds it."""
    from bonk_game.envs.utils.bodies import SlidingPlatform, Swing

    kind = spec["type"]
    if kind == "swing":
        _check_keys(spec, {"type", "pivot", "length", "seat_width"}, where)
        px, py = _numbers(_get(spec, "pivot", where), 2, f"{where}.pivot")
        length = _number(_get(spec, "length", where), f"{where}.length", 40)
        seat = _number(spec.get("seat_width", 96), f"{where}.seat_width", 50)
        return lambda: Swing(pivot_x=px, pivot_y=py, length=length, seat_width=seat)

    _check_keys(spec, {"type", "pieces", "travel", "mass", "rail"}, where)
    travel = _number(_get(spec, "travel", where), f"{where}.travel", 0)
    mass = _number(spec.get("mass", 6), f"{where}.mass", 0.5)
    rail = _get(spec, "rail", where, True, bool)
    parts = _get(spec, "pieces", where, kind=list)
    if not parts:
        _fail(f"{where}.pieces", "a slider needs at least one piece")
    makers = [_piece(p, f"{where}.pieces[{i}]") for i, p in enumerate(parts)]

    def build():
        platform = SlidingPlatform([m() for m in makers], mass=mass, travel=travel)
        platform.show_rail = rail
        return platform
    return build


# ---------------------------------------------------------------------------
# The map class
# ---------------------------------------------------------------------------
_TOP_KEYS = {"name", "title", "description", "rules", "spawn", "pieces"}
_RULE_KEYS = {"movement", "first_to", "round_time", "jump_speed", "max_speed", "on_death"}


def parse(data, source="map"):
    """Turn the decoded JSON of a map file into a Map class."""
    from bonk_game.envs.utils.maps import OpenMap

    where = source
    if not isinstance(data, dict):
        _fail(where, "the file should contain one JSON object")
    _check_keys(data, _TOP_KEYS, where)

    name = _get(data, "name", where, kind=str)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", name):
        _fail(f"{where}.name", f"{name!r} should be lowercase letters, digits and _ (it's used in file "
                               "and env names)")
    title = _get(data, "title", where, name.replace("_", " ").title(), str)
    description = _get(data, "description", where, "", str)

    rules = _get(data, "rules", where, {}, dict)
    _check_keys(rules, _RULE_KEYS, f"{where}.rules")
    movement = _get(rules, "movement", f"{where}.rules", "jump", str)
    if movement not in ("jump", "fly"):
        _fail(f"{where}.rules.movement", f'should be "jump" or "fly", got {movement!r}')
    on_death = _get(rules, "on_death", f"{where}.rules", "new_round", str)
    if on_death not in ("new_round", "respawn"):
        _fail(f"{where}.rules.on_death", f'should be "new_round" or "respawn", got {on_death!r}')
    first_to = _get(rules, "first_to", f"{where}.rules", 5, int)
    if isinstance(first_to, bool) or first_to < 1:
        _fail(f"{where}.rules.first_to", "should be a whole number of at least 1")

    attrs = dict(
        name=name, title=title, description=description,
        can_fly=movement == "fly",
        winning_score=first_to,
        reset_round_on_kill=on_death == "new_round",
        round_time=_number(rules.get("round_time", 45), f"{where}.rules.round_time", 0),
        jump_speed=_number(rules.get("jump_speed", OpenMap.jump_speed), f"{where}.rules.jump_speed", 0, 40),
        max_speed=_number(rules.get("max_speed", OpenMap.max_speed), f"{where}.rules.max_speed", 5, 40),
    )

    left, right, top, bottom = _numbers(_get(data, "spawn", where), 4, f"{where}.spawn")
    if right - left < 44 or bottom - top < 44:
        _fail(f"{where}.spawn", "should be [left, right, top, bottom] and at least 44 px each way "
                                "(players are 40 px across)")
    attrs["spawn_box"] = (left, right, top, bottom)

    pieces = _get(data, "pieces", where, kind=list)
    if not pieces:
        _fail(f"{where}.pieces", "a map needs at least one piece")
    static, bodies = [], []
    for i, spec in enumerate(pieces):
        w = f"{where}.pieces[{i}]"
        if isinstance(spec, dict) and spec.get("type") in BODY_TYPES:
            bodies.append((spec["type"], _body(spec, w)))
        else:
            static.append(_piece(spec, w))
    n_swings = sum(k == "swing" for k, _ in bodies)
    n_sliders = len(bodies) - n_swings
    attrs["n_extra_obs"] = 2 * (n_swings + n_sliders)
    attrs["_static"] = static
    attrs["_bodies"] = bodies
    attrs["source"] = source
    return type(f"FileMap_{name}", (FileMapMixin, OpenMap), attrs)


class FileMapMixin:
    """Behaviour shared by every map loaded from a file."""

    def reset(self):
        super().reset()
        self.blocks = [make() for make in self._static]
        self.bodies = [make() for _, make in self._bodies]
        self.swings = [b for b in self.bodies if hasattr(b, "theta")]
        self.sliders = [b for b in self.bodies if hasattr(b, "offset")]

    def extra_obs(self):
        values = []
        for s in self.swings:
            values += [s.theta / (np.pi / 2), s.omega / s.max_omega]
        for s in self.sliders:
            values += [s.offset / max(s.travel, 1), s.vx / s.max_speed]
        return np.clip(np.array(values, dtype=float), -1, 1)

    def safe_x_range(self):
        lo, hi = self.spawn_box[0], self.spawn_box[1]
        if self.sliders:
            off = self.sliders[0].offset
            return lo + off, hi + off
        return lo, hi

    def render(self, painter):
        for s in self.sliders:
            if getattr(s, "show_rail", False):
                ys = [b.rect()[3] for b in s.blocks]
                xs = [x for b in s.blocks for x in b.rect()[0::2]]
                painter.rail(min(xs) - s.offset - s.travel, max(xs) - s.offset + s.travel, max(ys) + 10)
        super().render(painter)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise MapFileError(f"{path}: not valid JSON (line {e.lineno}, column {e.colno}: {e.msg})") from None
    except OSError as e:
        raise MapFileError(f"{path}: can't read it ({e.strerror})") from None
    return parse(data, os.path.basename(path))


def map_dirs():
    dirs = [PACKAGE_MAPS, os.path.join(os.getcwd(), "maps")]
    dirs += [d for d in os.environ.get("BONK_MAPS", "").split(os.pathsep) if d]
    seen, out = set(), []
    for d in dirs:
        real = os.path.realpath(d)
        if real not in seen and os.path.isdir(d):
            seen.add(real)
            out.append(d)
    return out


def load_all(existing, warn=None):
    """Load every map file. Returns {name: class}; bad files are reported
    through `warn` (printed to stderr by default) and skipped."""
    warn = warn or (lambda msg: print(f"bonk_game: skipping map file. {msg}", file=sys.stderr))
    found = {}
    for d in map_dirs():
        for path in sorted(glob.glob(os.path.join(d, "*.json"))):
            try:
                cls = load_file(path)
            except MapFileError as e:
                warn(str(e))
                continue
            if cls.name in existing or cls.name in found:
                warn(f"{path}: there's already a map called {cls.name!r}")
                continue
            found[cls.name] = cls
    return found


def main(argv=None):
    paths = (argv if argv is not None else sys.argv[1:])
    if not paths:
        print("usage: python -m bonk_game.check_map MAP.json [...]")
        return 2
    ok = True
    for path in paths:
        try:
            cls = load_file(path)
            m = cls()
            print(f"{path}: ok ({cls.title!r}, {len(m.blocks)} pieces, {len(m.bodies)} moving parts)")
        except MapFileError as e:
            print(e)
            ok = False
    return 0 if ok else 1

