"""Your ball: favourite colour and pattern (web version)."""
import asyncio
import json
import re
from pathlib import Path

from bonk_game.server import cosmetics
from bonk_game.server import room as room_mod
from bonk_game.server.room import PATTERNS, Room
from bonk_game.ui import theme

CLIENT = Path(room_mod.__file__).parent / "static" / "js" / "core.js"


def test_the_client_knows_the_same_colours_and_patterns():
    js = CLIENT.read_text()
    palette = re.search(r"const PALETTE = \[(.*?)\];", js, re.S).group(1)
    pairs = re.findall(r'\["(\w+)", "(#[0-9a-f]{6})"\]', palette)
    assert [n for n, _ in pairs] == list(theme.PLAYER_NAMES)
    assert [c for _, c in pairs] == ["#%02x%02x%02x" % c for c in theme.PLAYER_COLORS]
    patterns = re.search(r"const PATTERNS = \[(.*?)\];", js, re.S).group(1)
    assert re.findall(r'"(\w+)"', patterns) == list(PATTERNS)
    names = re.search(r"const PATTERN_NAMES = \{(.*?)\};", js, re.S).group(1)
    assert dict(re.findall(r'(\w+): "([^"]+)"', names)) == dict(cosmetics.CATALOG["pattern"])


async def _room(*names):
    room = Room("TEST")
    sent = {n: [] for n in names}
    for n in names:
        async def send(msg, n=n):
            sent[n].append(msg if isinstance(msg, dict) else json.loads(msg))
        await room.join(n, n, send)
    return room, sent


def test_patterns_reach_the_lobby_and_the_match():
    async def go():
        room, sent = await _room("a", "b")
        await room.handle("b", {"type": "pattern", "pattern": "stars-and-moons"})
        await room.handle("b", {"type": "pattern", "pattern": "eyes"})
        assert room.lineup()[1]["pattern"] == "eyes"
        await room.start()
        slots = room.match.describe()["slots"]
        assert [s["pattern"] for s in slots[:2]] == ["plain", "eyes"]
        await room.stop()
    asyncio.run(go())


def test_a_saved_colour_that_is_taken_is_quietly_skipped():
    async def go():
        room, sent = await _room("a", "b")
        await room.handle("a", {"type": "color", "color": 3})
        sent["b"].clear()
        await room.handle("b", {"type": "color", "color": 3, "auto": True})
        assert not any(m["type"] == "error" for m in sent["b"])
        await room.handle("b", {"type": "color", "color": 3})
        assert any(m["type"] == "error" for m in sent["b"])
    asyncio.run(go())
