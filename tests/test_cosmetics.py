"""Cosmetics: patterns, trails, hats and knockout effects, unlocked by playing (#42)."""
import asyncio
import json

from bonk_game.server import cosmetics, profiles
from bonk_game.server.room import Room


def _profile(**stats):
    p = profiles.empty("x")
    awards = stats.pop("awards", {})
    p["stats"].update(stats)
    p["stats"]["awards"] = awards
    return p


def test_guests_get_the_free_ones_and_members_earn_the_rest():
    assert cosmetics.unlocked("pattern", "swirl", None)
    assert cosmetics.unlocked("ko", "pop", None)
    assert not cosmetics.unlocked("pattern", "galaxy", None)
    assert not cosmetics.unlocked("trail", "rainbow", None)
    fresh = _profile()
    assert cosmetics.unlocked("pattern", "galaxy", fresh) and cosmetics.unlocked("hat", "cap", fresh)
    assert not cosmetics.unlocked("trail", "rainbow", fresh)
    assert cosmetics.unlocked("trail", "rainbow", _profile(wins=10))
    assert cosmetics.unlocked("hat", "halo", fresh) and cosmetics.unlocked("pattern", "target", fresh)
    assert not cosmetics.unlocked("hat", "sombrero", fresh)


def test_nothing_is_locked_behind_awards():
    for items in cosmetics.CATALOG.values():
        for _i, _name, need in items:
            assert need in (None, "account") or need[0] in cosmetics.STAT_WORDS


def test_every_item_says_how_to_get_it():
    for kind, items in cosmetics.CATALOG.items():
        assert kind in cosmetics.KINDS and cosmetics.DEFAULT[kind] == items[0][0]
        assert len({i for i, _, _ in items}) == len(items)
        for i, _name, need in items:
            assert (cosmetics.how(need) == "") == (need is None)
            assert len(i) <= 16  # (profiles keep up to 16 characters)
    assert cosmetics.how(("wins", 10)) == "Win 10 matches (signed in)."
    assert cosmetics.problem("trail", "rainbow", _profile(wins=3)) == "Not unlocked yet: Win 10 matches (3 of 10)."
    assert cosmetics.problem("pattern", "galaxy", None) == "Sign in to use that pattern."
    assert cosmetics.problem("ko", "nope", None) == "Unknown knockout effect."


def test_the_catalogue_shows_progress():
    cat = cosmetics.catalog(_profile(kos=30))
    ghost = next(i for i in cat["ko"] if i["id"] == "ghost")
    assert ghost["unlocked"] and ghost["have"] == 30 and ghost["want"] == 25
    comet = next(i for i in cat["trail"] if i["id"] == "comet")
    assert not comet["unlocked"] and comet["have"] == 30 and comet["member"]
    assert all(not i["member"] for i in cat["pattern"][:10])


def test_the_room_checks_what_you_have_unlocked():
    class Inbox:
        def __init__(self):
            self.msgs = []

        async def __call__(self, msg):
            self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    accounts = {"u1": _profile(wins=12)}

    async def go():
        room = Room("ABCD", profile_of=accounts.get)
        guest, member = Inbox(), Inbox()
        await room.join("g", "Guest", guest)
        await room.join("m", "Member", member, account="u1")
        await room.handle("g", {"type": "look", "trail": "sparkle"})
        assert guest.msgs[-1]["message"] == "Sign in to use that one." and room.members["g"].trail == "none"
        await room.handle("g", {"type": "look", "pattern": "smile", "hat": "cap", "auto": True})
        assert room.members["g"].pattern == "smile" and room.members["g"].hat == "none"
        assert guest.msgs[-1]["type"] == "lobby"  # (auto: no error, but the pattern went through)
        await room.handle("m", {"type": "look", "trail": "rainbow", "hat": "tophat", "ko": "stars"})
        assert member.msgs[-2]["message"].startswith("Not unlocked yet: Win 25 matches (12 of 25)")
        m = room.members["m"]
        assert (m.trail, m.hat, m.ko) == ("rainbow", "none", "stars")
        seat = next(s for s in member.msgs[-1]["seats"] if s["id"] == room.members["m"].pid)
        assert seat["trail"] == "rainbow" and seat["ko"] == "stars"
        await room.start()
        slot = next(s for s in room.match.describe()["slots"] if s["id"] == room.members["m"].pid)
        assert (slot["pattern"], slot["trail"], slot["hat"], slot["ko"]) == ("plain", "rainbow", "none", "stars")
        await room.stop()
    asyncio.run(go())


def test_profiles_keep_the_look():
    p = profiles.validate({**profiles.empty("a"), "trail": "comet", "hat": 5})
    assert p["trail"] == "comet" and p["hat"] == "none" and p["ko"] == "pop"
