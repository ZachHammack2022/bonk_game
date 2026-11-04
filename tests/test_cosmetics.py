"""Cosmetics: patterns, trails, hats and knockout effects (#42). Everything
is available to everyone."""
import asyncio
import json

from bonk_game.server import cosmetics, profiles
from bonk_game.server.room import Room


def test_everyone_can_wear_everything():
    member = profiles.empty("x")
    for kind, items in cosmetics.CATALOG.items():
        for i, _name in items:
            assert cosmetics.unlocked(kind, i, None) and cosmetics.unlocked(kind, i, member)
            assert cosmetics.problem(kind, i, None) is None
    for items in cosmetics.catalog(None).values():
        assert all(i["unlocked"] for i in items)


def test_the_catalogue_is_well_formed():
    for kind, items in cosmetics.CATALOG.items():
        assert kind in cosmetics.KINDS and cosmetics.DEFAULT[kind] == items[0][0]
        assert len({i for i, _ in items}) == len(items)
        assert all(len(i) <= 16 for i, _ in items)  # (profiles keep up to 16 characters)
    assert not cosmetics.unlocked("hat", "sombrero")
    assert cosmetics.problem("ko", "nope", None) == "Unknown knockout effect."
    assert cosmetics.problem("pattern", "nope", None) == "Unknown pattern."


def test_the_room_lets_a_guest_wear_anything_but_not_made_up_things():
    class Inbox:
        def __init__(self):
            self.msgs = []

        async def __call__(self, msg):
            self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    async def go():
        room = Room("ABCD")
        guest = Inbox()
        await room.join("g", "Guest", guest)
        await room.handle("g", {"type": "look", "trail": "rainbow", "hat": "halo", "ko": "fireworks"})
        await room.handle("g", {"type": "pattern", "pattern": "galaxy"})
        m = room.members["g"]
        assert (m.trail, m.hat, m.ko, m.pattern) == ("rainbow", "halo", "fireworks", "galaxy")
        await room.handle("g", {"type": "look", "hat": "crown of lies"})
        assert m.hat == "halo"
    asyncio.run(go())
