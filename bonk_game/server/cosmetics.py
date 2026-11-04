"""Cosmetics: what a ball can wear (issue #42).

Four kinds of thing, each a list of (id, name):
- pattern: drawn on the ball
- trail:   follows the ball around
- hat:     sits on top of it
- ko:      what it looks like when the ball is knocked out

Everything is available to everyone, guests included: nothing is locked
behind signing in, playing a lot or the end-of-match awards.

The browser gets the catalogue from /api/me (auth.py), so this file is the
only list. The server checks every pick (problem()), so only real items
are worn.
"""
KINDS = ("pattern", "trail", "hat", "ko")
DEFAULT = {"pattern": "plain", "trail": "none", "hat": "none", "ko": "pop"}

CATALOG = {
    "pattern": [
        ("plain", "Plain"), ("stripes", "Stripes"), ("dots", "Dots"),
        ("ring", "Ring"), ("split", "Split"), ("star", "Star"),
        ("zigzag", "Zigzag"), ("eyes", "Eyes"), ("swirl", "Swirl"),
        ("smile", "Smile"),
        ("heart", "Heart"), ("checker", "Checker"), ("galaxy", "Galaxy"),
        ("flame", "Flame"), ("bolt", "Bolt"),
        ("target", "Target"),
    ],
    "trail": [
        ("none", "None"),
        ("sparkle", "Sparkle"),
        ("bubbles", "Bubbles"),
        ("rainbow", "Rainbow"),
        ("comet", "Comet"),
    ],
    "hat": [
        ("none", "None"),
        ("cap", "Cap"),
        ("party", "Party hat"),
        ("tophat", "Top hat"),
        ("halo", "Halo"),
        ("horns", "Horns"),
    ],
    "ko": [
        ("pop", "Pop"),
        ("confetti", "Confetti"),
        ("stars", "Stars"),
        ("ghost", "Ghost"),
        ("fireworks", "Fireworks"),
    ],
}
IDS = {kind: tuple(i for i, _ in items) for kind, items in CATALOG.items()}


def unlocked(kind, item, profile=None):
    """Can someone wear `item`? Anyone can wear anything in the catalogue.
    (profile: kept so callers don't need to change.)"""
    return item in IDS.get(kind, ())


def problem(kind, item, profile=None):
    """Why someone can't wear `item` (it doesn't exist), or None if they can."""
    if kind not in CATALOG or item not in IDS[kind]:
        return "Unknown " + {"ko": "knockout effect"}.get(kind, kind) + "."
    return None


def catalog(profile=None):
    """The catalogue for the browser: {kind: [{id, name, unlocked}]}."""
    return {kind: [{"id": i, "name": name, "unlocked": True} for i, name in items]
            for kind, items in CATALOG.items()}
