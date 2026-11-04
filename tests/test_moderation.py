"""Moderation basics (#36): the name filter, reports and what the room keeps for them."""
import asyncio
import json
import random

import pytest

from bonk_game.server import moderation
from bonk_game.server.room import Room


class Inbox:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg):
        self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    def last(self, kind):
        return next(m for m in reversed(self.msgs) if m["type"] == kind)


@pytest.mark.parametrize("name", ["fuck", "F4CK", "f u c k", "fuuuuck", "sh!t head", "big dick",
                                  "n1gg3r", "kys", "KKK", "xXhitlerXx", "d.i.c.k"])
def test_offensive_names_are_caught(name):
    assert moderation.offensive(name)


@pytest.mark.parametrize("name", ["Sam", "Dickens", "grapes", "therapist", "torpedo", "Assassin",
                                  "Class", "peacock", "Raccoon", "spice", "Kirk", "Bass", "Shell",
                                  "Zack", "Cocoa", "Hancock"])
def test_ordinary_names_are_left_alone(name):
    assert not moderation.offensive(name)


def test_an_offensive_name_is_replaced_not_refused():
    name, replaced = moderation.clean_name("  fuck   you ", rng=random.Random(1))
    assert replaced and name.startswith("Player ") and len(name) == 9
    assert moderation.clean_name("  Sam   B ") == ("Sam B", False)
    assert moderation.clean_name("") == ("Player", False)

    async def go():
        room = Room("ABCD")
        a = Inbox()
        await room.join("a", "shithead", a)
        assert room.members["a"].name.startswith("Player ")
        assert "isn't allowed" in a.last("notice")["message"]
        await room.handle("a", {"type": "name", "name": "Ann"})
        assert room.members["a"].name == "Ann"
        await room.handle("a", {"type": "name", "name": "cunt"})
        assert room.members["a"].name.startswith("Player ")
        assert [e["e"] for e in room.recent] == ["name_filtered", "join", "name", "name_filtered", "name"]
    asyncio.run(go())


def test_reporting_a_player():
    async def go():
        moderation.REPORTS.items.clear()
        room = Room("ABCD")
        a, b = Inbox(), Inbox()
        await room.join("a", "Ann", a, account="acc-a")
        await room.join("b", "Bob", b)
        await room.handle("b", {"type": "name", "name": "Bobby"})
        pid = room.members["b"].pid
        await room.handle("a", {"type": "report_player", "id": pid, "reason": "emotes",
                                "note": "  spam\nspam  " + "x" * 500})
        assert "Thanks" in a.last("notice")["message"]
        [rep] = moderation.REPORTS.items
        assert rep["room"] == "ABCD" and rep["reason"] == "emotes"
        assert rep["reporter"] == {"name": "Ann", "account": "acc-a"}
        assert rep["reported"]["name"] == "Bobby" and rep["reported"]["names"] == ["Bob", "Bobby"]
        assert len(rep["note"]) == moderation.REPORT_NOTE_LEN and "\n" not in rep["note"]
        assert [e["e"] for e in rep["recent"]] == ["join", "join", "name"]
        # Once per person, and not too many
        await room.handle("a", {"type": "report_player", "id": pid, "reason": "name"})
        assert "already" in a.last("notice")["message"] and len(moderation.REPORTS.items) == 1
        await room.handle("a", {"type": "report_player", "id": room.members["a"].pid})
        assert len(moderation.REPORTS.items) == 1  # (not yourself)
        for k in range(4):
            await room.join(f"x{k}", "X", Inbox())
            await room.handle("a", {"type": "report_player", "id": room.members[f"x{k}"].pid, "reason": "?"})
        assert len(moderation.REPORTS.items) == moderation.REPORTS_PER_MINUTE
        assert moderation.REPORTS.items[-1]["reason"] == "other"
        assert "a lot of reports" in a.last("error")["message"]
    asyncio.run(go())
