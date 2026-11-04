"""Cosmetics: what a ball can wear (issue #42).

Four kinds of thing, each a list of (id, name, members):
- pattern: drawn on the ball
- trail:   follows the ball around
- hat:     sits on top of it
- ko:      what it looks like when the ball is knocked out

members: True for the few things that are for signed-in players. Signing
in is all it takes: nothing is earned by playing a lot or by winning
awards. Everything else is for everyone, guests included. (Signed-in
players also get any colour for their ball: room.pick_own_color.)

The browser gets the catalogue from /api/me (auth.py). The server checks
every pick (problem()), so a guest can't wear a members' item.
"""
KINDS = ("pattern", "trail", "hat", "ko")
DEFAULT = {"pattern": "plain", "trail": "none", "hat": "none", "ko": "pop"}

CATALOG = {
    "pattern": [
        ("plain", "Plain", False), ("stripes", "Stripes", False), ("dots", "Dots", False),
        ("ring", "Ring", False), ("split", "Split", False), ("star", "Star", False),
        ("zigzag", "Zigzag", False), ("eyes", "Eyes", False), ("swirl", "Swirl", False),
        ("smile", "Smile", False),
        ("heart", "Heart", True), ("checker", "Checker", True), ("galaxy", "Galaxy", True),
        ("flame", "Flame", False), ("bolt", "Bolt", False),
        ("target", "Target", False),
    ],
    "trail": [
        ("none", "None", False),
        ("sparkle", "Sparkle", True),
        ("bubbles", "Bubbles", False),
        ("rainbow", "Rainbow", False),
        ("comet", "Comet", False),
    ],
    "hat": [
        ("none", "None", False),
        ("cap", "Cap", True),
        ("party", "Party hat", False),
        ("tophat", "Top hat", False),
        ("halo", "Halo", False),
        ("horns", "Horns", False),
    ],
    "ko": [
        ("pop", "Pop", False),
        ("confetti", "Confetti", True),
        ("stars", "Stars", False),
        ("ghost", "Ghost", False),
        ("fireworks", "Fireworks", False),
    ],
}
IDS = {kind: tuple(i for i, _, _ in items) for kind, items in CATALOG.items()}
_MEMBERS = {(kind, i) for kind, items in CATALOG.items() for i, _, members in items if members}
HOW = "Sign in to use it."


def unlocked(kind, item, signed_in=False):
    """Can someone wear `item`? Members' items need signing in."""
    if item not in IDS.get(kind, ()):
        return False
    return signed_in or (kind, item) not in _MEMBERS


def problem(kind, item, signed_in=False):
    """Why someone can't wear `item`, or None if they can."""
    if kind not in CATALOG or item not in IDS[kind]:
        return "Unknown " + {"ko": "knockout effect"}.get(kind, kind) + "."
    if not unlocked(kind, item, signed_in):
        return f"Sign in to use that {'pattern' if kind == 'pattern' else 'one'}."
    return None


def catalog(signed_in=False):
    """The catalogue for the browser: {kind: [{id, name, member, unlocked, how}]}."""
    return {kind: [{"id": i, "name": name, "member": members,
                    "unlocked": unlocked(kind, i, signed_in), "how": HOW if members else ""}
                   for i, name, members in items]
            for kind, items in CATALOG.items()}
