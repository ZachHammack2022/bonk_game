"""Cosmetics: what a ball can wear, and how you unlock it (issue #42).

Four kinds of thing, each a list of (id, name, need):
- pattern: drawn on the ball
- trail:   follows the ball around
- hat:     sits on top of it
- ko:      what it looks like when the ball is knocked out

`need` says who can use it:
- None:                  everyone, guests too
- "account":             anyone signed in
- ("wins", 5) and so on: signed in, with that many in your stats (the
                         server records every match an account plays, so
                         these are earned by playing)

Nothing is ever locked behind the end-of-match awards (most knockouts,
hardest hit, survivor...): they're for fun, not a grind.

The browser gets the catalogue and what you've unlocked from /api/cosmetics
(web.py), so this file is the only list. The server checks every pick
(allowed()), so nobody wears something they haven't unlocked.
"""
KINDS = ("pattern", "trail", "hat", "ko")
DEFAULT = {"pattern": "plain", "trail": "none", "hat": "none", "ko": "pop"}

CATALOG = {
    "pattern": [
        ("plain", "Plain", None), ("stripes", "Stripes", None), ("dots", "Dots", None),
        ("ring", "Ring", None), ("split", "Split", None), ("star", "Star", None),
        ("zigzag", "Zigzag", None), ("eyes", "Eyes", None), ("swirl", "Swirl", None),
        ("smile", "Smile", None),
        ("heart", "Heart", "account"), ("checker", "Checker", "account"), ("galaxy", "Galaxy", "account"),
        ("flame", "Flame", ("wins", 5)), ("bolt", "Bolt", ("kos", 50)),
        ("target", "Target", "account"),
    ],
    "trail": [
        ("none", "None", None),
        ("sparkle", "Sparkle", "account"),
        ("bubbles", "Bubbles", ("matches", 10)),
        ("rainbow", "Rainbow", ("wins", 10)),
        ("comet", "Comet", ("kos", 100)),
    ],
    "hat": [
        ("none", "None", None),
        ("cap", "Cap", "account"),
        ("party", "Party hat", ("matches", 25)),
        ("tophat", "Top hat", ("wins", 25)),
        ("halo", "Halo", "account"),
        ("horns", "Horns", ("kos", 250)),
    ],
    "ko": [
        ("pop", "Pop", None),
        ("confetti", "Confetti", "account"),
        ("stars", "Stars", ("wins", 3)),
        ("ghost", "Ghost", ("kos", 25)),
        ("fireworks", "Fireworks", ("wins", 50)),
    ],
}
IDS = {kind: tuple(i for i, _, _ in items) for kind, items in CATALOG.items()}
_NEED = {(kind, i): need for kind, items in CATALOG.items() for i, _, need in items}
STAT_WORDS = {"matches": ("Play", "matches"), "wins": ("Win", "matches"), "kos": ("Knock out", "players")}


def _progress(need, profile):
    """(have, want) for a stat need."""
    stats = profile["stats"] if profile else {}
    return stats.get(need[0], 0), need[1]


def unlocked(kind, item, profile):
    """Can someone wear `item`? profile: their account's profile (profiles.py),
    or None for a guest."""
    if (kind, item) not in _NEED:
        return False
    need = _NEED[(kind, item)]
    if need is None:
        return True
    if profile is None:
        return False
    if need == "account":
        return True
    have, want = _progress(need, profile)
    return have >= want


def how(need):
    """How to unlock something, in words."""
    if need is None:
        return ""
    if need == "account":
        return "Sign in to use it."
    verb, noun = STAT_WORDS[need[0]]
    return f"{verb} {need[1]} {noun} (signed in)."


def problem(kind, item, profile):
    """Why someone can't wear `item`, or None if they can."""
    if kind not in CATALOG or (kind, item) not in _NEED:
        return "Unknown " + {"ko": "knockout effect"}.get(kind, kind) + "."
    if unlocked(kind, item, profile):
        return None
    need = _NEED[(kind, item)]
    if need == "account":
        return f"Sign in to use that {'pattern' if kind == 'pattern' else 'one'}."
    have, want = _progress(need, profile)
    return f"Not unlocked yet: {how(need)[:-1].replace(' (signed in)', '')} ({have} of {want})."


def catalog(profile):
    """The catalogue for the browser, with what this person has unlocked:
    {kind: [{id, name, how, unlocked, have, want}]}."""
    out = {}
    for kind, items in CATALOG.items():
        out[kind] = []
        for i, name, need in items:
            entry = {"id": i, "name": name, "how": how(need), "unlocked": unlocked(kind, i, profile),
                     "member": need is not None}
            if isinstance(need, tuple):
                entry["have"], entry["want"] = _progress(need, profile)
            out[kind].append(entry)
    return out

