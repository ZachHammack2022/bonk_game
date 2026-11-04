"""Game speed (stepping.TIME_SCALE and the room's Speed setting): the world
in slow motion, with the same paths."""
import asyncio

import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils import stepping
from bonk_game.envs.utils.controls import Buttons
from bonk_game.server.lobby import SPEEDS

UP = Buttons(True, False, False, False, False)
RIGHT = Buttons(False, False, False, True, False)


def jump(time_scale):
    """(height, ticks to the top) of a standing jump."""
    env = TestEnv("human", "human", map_name="platform", time_scale=time_scale)
    env.reset()
    env.timer.limit = 0
    a, b = env.players
    a.x, a.y, b.x, b.y = 400, 270, 220, 270
    for _ in range(20):
        env.step()
    y0 = best = a.y
    top = 0
    for t in range(120):
        env.step([UP, None])  # (held: a hovering jump, for a longer arc)
        if a.y < best:
            best, top = a.y, t
    return y0 - best, top


def test_the_default_is_slower_than_the_original():
    assert stepping.TIME_SCALE < 1
    assert SPEEDS["fast"] == 1.0 and SPEEDS["normal"] == stepping.TIME_SCALE < 1 and SPEEDS["slow"] < SPEEDS["normal"]


def test_slow_motion_jumps_as_high_but_takes_longer():
    h_fast, t_fast = jump(1.0)
    h_slow, t_slow = jump(0.6)
    # (within a few %: hovering is a push once a step, gravity every substep)
    assert h_slow == pytest.approx(h_fast, rel=0.08)
    assert t_slow == pytest.approx(t_fast / 0.6, rel=0.15)


def test_running_takes_longer_to_get_up_to_speed():
    def run(time_scale):
        env = TestEnv("human", "human", map_name="platform", time_scale=time_scale)
        env.reset()
        env.timer.limit = 0
        a, b = env.players
        a.x, a.y, b.x, b.y = 220, 270, 460, 270
        for _ in range(10):
            env.step()
        x0 = a.x
        for _ in range(10):
            env.step([RIGHT, None])
        return a.x - x0

    # Slower world: less ground covered in the same time (about time_scale²
    # for a run starting from standing still)
    assert run(0.75) == pytest.approx(run(1.0) * 0.75 ** 2, rel=0.1)


def test_heavy_lasts_longer_in_slow_motion():
    def heavy_ticks(time_scale):
        env = TestEnv("human", "human", map_name="platform", time_scale=time_scale)
        env.reset()
        p = env.players[0]
        p.make_heavy()
        t = 0
        while p.m > p.min_m:
            env.step()
            t += 1
        return t

    assert heavy_ticks(0.5) == pytest.approx(2 * heavy_ticks(1.0), abs=2)


def test_speed_setting_in_a_room():
    from bonk_game.server.room import RoomManager

    class Inbox:
        def __init__(self):
            self.msgs = []

        async def __call__(self, msg):
            self.msgs.append(msg)

    async def go():
        room = RoomManager().create()
        await room.join("a", "Ann", Inbox())
        await room.handle("a", {"type": "settings", "speed": "warp"})
        assert room.settings["speed"] == "normal"
        await room.handle("a", {"type": "settings", "speed": "fast"})
        assert room.settings["speed"] == "fast"
        await room.start()
        assert room.match.env.time_scale == 1.0
        assert room.match.physics()["time_scale"] == 1.0
        assert room.match.options["speed"] == 1.0
        await room.stop()
    asyncio.run(go())
