"""Cosmetics: patterns, trails, hats and knockout effects (#42). A few are
for signed-in players (signing in is all it takes); everything else is for
everyone."""
import asyncio
import json

from bonk_game.server import cosmetics
from bonk_game.server.room import Room

MEMBERS = {("pattern", "heart"), ("pattern", "checker"), ("pattern", "galaxy"),
           ("trail", "sparkle"), ("hat", "cap"), ("ko", "confetti")}


def test_a_few_things_are_for_signed_in_players_and_the_rest_for_everyone():
    for kind, items in cosmetics.CATALOG.items():
        for i, _name, members in items:
            assert members == ((kind, i) in MEMBERS)
            assert cosmetics.unlocked(kind, i, signed_in=True)
            assert cosmetics.unlocked(kind, i, signed_in=False) == (not members)
    # Things that used to be earned by playing are free now
    for kind, i in (("trail", "rainbow"), ("hat", "halo"), ("ko", "fireworks"), ("pattern", "target")):
        assert cosmetics.unlocked(kind, i)


def test_nothing_is_earned_by_playing():
    # Only two tiers: everyone, or signed in. No stats, no awards.
    for items in cosmetics.CATALOG.values():
        for _i, _name, members in items:
            assert members in (True, False)


def test_the_catalogue_says_whats_locked():
    guest, member = cosmetics.catalog(False), cosmetics.catalog(True)
    galaxy = next(i for i in guest["pattern"] if i["id"] == "galaxy")
    assert not galaxy["unlocked"] and galaxy["member"] and galaxy["how"] == "Sign in to use it."
    assert all(i["unlocked"] for items in member.values() for i in items)
    for kind, items in cosmetics.CATALOG.items():
        assert kind in cosmetics.KINDS and cosmetics.DEFAULT[kind] == items[0][0]
        assert not items[0][2]  # (the default is never locked)
        assert len({i for i, _, _ in items}) == len(items)
    assert cosmetics.problem("pattern", "galaxy") == "Sign in to use that pattern."
    assert cosmetics.problem("ko", "nope") == "Unknown knockout effect."


def test_the_room_checks_who_is_signed_in():
    class Inbox:
        def __init__(self):
            self.msgs = []

        async def __call__(self, msg):
            self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    async def go():
        room = Room("ABCD")
        await room.join("g", "Guest", Inbox())
        await room.join("m", "Member", Inbox(), account="u1")
        for t in ("g", "m"):
            await room.handle(t, {"type": "look", "trail": "rainbow", "hat": "cap"})
        g, m = room.members["g"], room.members["m"]
        assert (g.trail, g.hat) == ("rainbow", "none")
        assert (m.trail, m.hat) == ("rainbow", "cap")
    asyncio.run(go())
