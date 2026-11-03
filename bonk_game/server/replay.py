"""Replays: a match's seed and inputs, played back through the same physics.

A replay file is small (every player's input only when it changes) and is
exactly the match: play() runs the physics again and gives the same state,
tick for tick, as the players saw.

    {"format": "bonk-replay", "v": 1, "engine": "<hash of the physics code>",
     "map": "platform", "mode": "ffa", "first_to": 5, "round_time": null,
     "gravity": 1.0, "power_ups": false, "seed": 123,
     "slots": [{"name", "kind", "color", "team"}],    no tokens: anyone can share it
     "inputs": [[physics step, slot, input code], ...],   (match.input_code)
     "ticks": 2500, "match_id": "ABCD-1700000000000", "at": 1700000000}

A file made by different physics code (another version of the game) may
play out differently; `engine` says which code made it.
"""
import hashlib
from pathlib import Path

from bonk_game.envs.utils.maps import MAPS
from bonk_game.server import modes
from bonk_game.server.match import Match

FORMAT = "bonk-replay"
VERSION = 1
MAX_TICKS = 30 * 60 * 30    # half an hour
MAX_INPUTS = 400_000

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_FILES = sorted([*(_ROOT / "envs").rglob("*.py"),
                        *(_ROOT / "server" / n for n in ("match.py", "modes.py", "powerups.py"))])
ENGINE = hashlib.sha256(b"".join(p.read_bytes() for p in _ENGINE_FILES)).hexdigest()[:12]


class BadReplay(ValueError):
    pass


def record(match, ticks, match_id=None, at=None):
    """The replay file for a match that has been played (`ticks` ticks)."""
    return {"format": FORMAT, "v": VERSION, "engine": ENGINE, "map": match.map_name, **match.options,
            "seed": match.seed,
            "slots": [{"name": s["name"], "kind": s["kind"], "color": match.colors[i],
                       "team": s.get("team")} for i, s in enumerate(match.slots)],
            "inputs": [list(x) for x in match.recording], "ticks": ticks,
            "match_id": match_id, "at": at}


def _int(v, lo, hi, what):
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise BadReplay(f"bad {what}")
    return v


def check(rep):
    """A replay file as one we can play, or BadReplay saying why not."""
    if not isinstance(rep, dict) or rep.get("format") != FORMAT:
        raise BadReplay("not a bonk replay")
    if rep.get("v") != VERSION:
        raise BadReplay("a replay from a newer version of the game")
    if rep.get("map") not in MAPS:
        raise BadReplay("unknown map")
    if rep.get("mode") not in modes.MODES:
        raise BadReplay("unknown mode")
    slots = rep.get("slots")
    if not isinstance(slots, list) or not 2 <= len(slots) <= 10:
        raise BadReplay("bad players")
    clean_slots = []
    for s in slots:
        if not isinstance(s, dict):
            raise BadReplay("bad players")
        team = s.get("team")
        clean_slots.append({"name": str(s.get("name", "?"))[:16], "kind": "human",
                            "was": str(s.get("kind", "human"))[:32],
                            "color": _int(s.get("color", 0), 0, 9, "colour"),
                            "team": team if team in (0, 1) else None})
    inputs = rep.get("inputs")
    if not isinstance(inputs, list) or len(inputs) > MAX_INPUTS:
        raise BadReplay("bad inputs")
    clean_inputs, last = [], 0
    for x in inputs:
        if not isinstance(x, list) or len(x) != 3:
            raise BadReplay("bad inputs")
        step = _int(x[0], last, MAX_TICKS, "input step")
        clean_inputs.append([step, _int(x[1], 0, len(slots) - 1, "input slot"),
                             _int(x[2], -1, 32 + 63, "input")])
        last = step
    goal = rep.get("first_to")
    if not isinstance(goal, (int, float)) or isinstance(goal, bool) or not 0 < goal <= 600:
        raise BadReplay("bad goal")
    rt = rep.get("round_time")
    if rt is not None and (not isinstance(rt, (int, float)) or isinstance(rt, bool) or not 0 <= rt <= 3600):
        raise BadReplay("bad round time")
    gravity = rep.get("gravity", 1.0)
    if not isinstance(gravity, (int, float)) or isinstance(gravity, bool) or not 0.1 <= gravity <= 5:
        raise BadReplay("bad gravity")
    return {**rep, "slots": clean_slots, "inputs": clean_inputs, "first_to": goal, "round_time": rt,
            "gravity": float(gravity), "power_ups": rep.get("power_ups") is True,
            "seed": _int(rep.get("seed"), 0, 2 ** 31, "seed"),
            "ticks": _int(rep.get("ticks"), 1, MAX_TICKS, "length")}


def rebuild(rep):
    """A Match that plays a (checked) replay back."""
    slots = [{"kind": "human", "name": s["name"], "color": s["color"],
              **({"team": s["team"]} if s["team"] is not None else {})} for s in rep["slots"]]
    match = Match(rep["map"], slots, rep["first_to"], mode=rep["mode"], round_time=rep["round_time"],
                  gravity=rep["gravity"], power_ups=rep["power_ups"], seed=rep["seed"], replay=rep["inputs"])
    for s, r in zip(match.slots, rep["slots"]):
        s["kind"] = r["was"]  # (for showing who was a bot; everyone's inputs come from the file)
    return match


def play(rep):
    """(match, generator of (state, events) for each tick), like the room's
    loop. `rep` must have been check()ed."""
    match = rebuild(rep)

    def ticks():
        for _ in range(rep["ticks"]):
            events = match.tick()
            yield match.snapshot(), events
            if match.finished:
                break
    return match, ticks()
