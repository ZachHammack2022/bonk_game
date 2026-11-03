"""How many players each map is for, and the lobby holding to it."""
import asyncio
import json

import pytest

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.map_files import MapFileError, parse
from bonk_game.envs.utils.maps import MAPS
from bonk_game.server.room import Room

BIG = ["grand", "decks"]


def test_every_map_has_a_sensible_range():
    for name, m in MAPS.items():
        lo, hi = m.players
        assert arena.MIN_PLAYERS <= lo <= hi <= arena.MAX_PLAYERS, name


@pytest.mark.parametrize("name", BIG)
def test_big_maps_fit_ten_and_spawn_everyone_on_solid_ground(name):
    from bonk_game.envs.testing_env import TestEnv
    assert MAPS[name].players[1] == 10
    env = TestEnv(*[None] * 10, map_name=name)
    for seed in range(5):
        env.reset()
        for _ in range(60):  # two seconds of nobody touching anything
            _, _, info = env.step()
            assert not info["deaths"], f"someone fell on spawning (seed {seed})"


def test_map_files_take_a_player_range():
    base = {"name": "x", "spawn": [100, 300, 100, 300], "pieces": [{"type": "block", "rect": [0, 300, 400, 320]}]}
    assert parse({**base, "rules": {"players": [3, 7]}}).players == (3, 7)
    assert parse(base).players == (2, 10)
    for bad in ([1, 4], [5, 4], [2, 11], [2], [2.5, 4], [True, 4]):
        with pytest.raises(MapFileError):
            parse({**base, "rules": {"players": bad}})


async def _room(*names):
    room = Room("TEST")
    for n in names:
        async def send(msg):
            pass
        await room.join(n, n, send)
    return room


def test_bots_past_the_maps_limit_sit_out():
    async def go():
        room = await _room("a")
        await room.handle("a", {"type": "settings", "map": "grand", "bots": ["bot:easy"] * 9})
        assert len(room.lineup()) == 10
        await room.handle("a", {"type": "settings", "map": "platform"})
        assert len(room.lineup()) == MAPS["platform"].players[1]
        # Back on a big map, they're all there again
        await room.handle("a", {"type": "settings", "map": "decks"})
        assert len(room.lineup()) == 10
    asyncio.run(go())


def test_small_maps_refuse_a_crowd_and_big_maps_need_one():
    async def go():
        names = [f"p{i}" for i in range(7)]
        room = await _room(*names)
        await room.handle("p0", {"type": "settings", "map": "grand", "bots": []})
        await room.handle("p0", {"type": "settings", "map": "platform"})
        assert room.settings["map"] == "grand"  # 7 people won't fit on a 6-player map
        solo = await _room("a")
        errors = []

        async def send(msg):
            msg = msg if isinstance(msg, dict) else json.loads(msg)
            if msg["type"] == "error":
                errors.append(msg["message"])
        solo.members["a"].send = send
        await solo.handle("a", {"type": "settings", "map": "grand", "bots": ["bot:easy"]})
        await solo.start()
        assert solo.match is None and "at least 4" in errors[-1]
    asyncio.run(go())
