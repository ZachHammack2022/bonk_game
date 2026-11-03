"""Smaller state messages: send what changed since the last tick.

A match sends a full "state" now and then (a keyframe) and a delta ("d")
every other tick. A delta has only the fields that changed:

    {"type": "d", "tick": 42, "players": {"3": [...]}, "level": {"5": {"r": [...]}}}

- It builds on the state for tick - 1 (or "base", if that's another tick).
  The browser applies it only if the last state it has is that tick;
  otherwise it waits for the next keyframe.
- A field whose value is a list that kept its length (players, level,
  scores...) is sent as {index: new item} for the items that changed. An
  item that is a dict (a level shape) is sent as just its changed keys.
- Anything else that changed is sent whole. Fields that went away are
  listed in "gone".
- "events" (sounds, knockouts...) are new every tick: sent when there are
  any, and an empty list otherwise.

static/delta.js does the same as apply() in the browser, and
tests/test_delta.py checks both rebuild every state exactly.
"""
KEYFRAME_EVERY = 90   # ticks (3 s): a full state now and then, in case
RESERVED = ("type", "base", "gone")


def _same(a, b):
    return a == b and type(a) is type(b)


def _item_patch(old, new):
    """What to send for one changed list item: a dict sends only its changed
    keys (None if a key went away: then send the whole list)."""
    if isinstance(old, dict) and isinstance(new, dict):
        if any(k not in new for k in old):
            return None
        return {k: v for k, v in new.items() if not _same(old.get(k, _MISSING), v)}
    return new


def diff(prev, cur):
    """The delta from state `prev` to state `cur` (both full "state" dicts),
    or None if a keyframe is needed instead."""
    out = {"type": "d"}
    if cur["tick"] != prev["tick"] + 1:
        out["base"] = prev["tick"]
    for k, v in cur.items():
        if k in ("type", "events"):
            continue
        if k in RESERVED:
            return None
        old = prev.get(k, _MISSING)
        if _same(old, v):
            continue
        if isinstance(old, list) and isinstance(v, list) and len(old) == len(v):
            patch = {str(i): _item_patch(a, item) for i, (a, item) in enumerate(zip(old, v))
                     if not _same(a, item)}
            out[k] = v if None in patch.values() else patch
        elif isinstance(old, list) and isinstance(v, dict):
            return None  # would read as a patch
        else:
            out[k] = v
    gone = [k for k in prev if k not in cur and k not in ("type", "events")]
    if gone:
        out["gone"] = gone
    if cur.get("events"):
        out["events"] = cur["events"]
    return out


def apply(prev, d):
    """Rebuild the full state from the one before and a delta (what
    static/delta.js does)."""
    base = d.get("base", d["tick"] - 1)
    if base != prev["tick"]:
        raise ValueError(f"delta for tick {base} applied to tick {prev['tick']}")
    s = {k: v for k, v in prev.items() if k not in d.get("gone", ())}
    s["type"] = "state"
    s["events"] = []
    for k, v in d.items():
        if k in RESERVED:
            continue
        if isinstance(s.get(k), list) and isinstance(v, dict):
            items = list(s[k])
            for i, item in v.items():
                old = items[int(i)]
                items[int(i)] = {**old, **item} if isinstance(old, dict) else item
            s[k] = items
        else:
            s[k] = v
    return s


class Encoder:
    """Turns each tick's full state into the message to send."""

    def __init__(self, keyframe_every=None):
        self.every = keyframe_every or KEYFRAME_EVERY  # 1: full states only
        self.last = None    # the last full state sent
        self.count = 0

    def encode(self, state):
        d = None
        if self.last is not None and self.count % self.every:
            d = diff(self.last, state)
        self.last = state
        self.count += 1
        return state if d is None else d

    def keyframe(self):
        """The latest full state, for someone who just arrived (no events:
        they already happened)."""
        return None if self.last is None else {**self.last, "events": []}


class _Missing:
    def __eq__(self, other):
        return False


_MISSING = _Missing()
