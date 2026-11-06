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
    falling = False
    for t in range(120):
        env.step([UP, None])  # (held: a hovering jump, for a longer arc)
        if falling and a.y_v < 0:
            break  # landed (just the one jump: held, it pogos on landing)
        falling = a.y_v > 0
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
    def run(time_scale, ticks):
        env = TestEnv("human", "human", map_name="platform", time_scale=time_scale)
        env.reset()
        env.timer.limit = 0
        a, b = env.players
        a.x, a.y, b.x, b.y = 220, 270, 460, 270
        for _ in range(10):
            env.step()
        x0 = a.x
        for _ in range(ticks):
            env.step([RIGHT, None])
        return a.x - x0

    # Slower world: less ground covered in the same time...
    assert run(0.75, 12) < run(1.0, 12) * 0.8
    # ...but the same run, just taking longer (grip included)
    assert run(0.75, 16) == pytest.approx(run(1.0, 12), rel=0.05)


HEAVY_RIGHT = Buttons(False, False, False, True, True)


def sprint(buttons, ticks=65):
    """Run right along Grand Stage's long floor at normal speed: (top speed
    in px a second, px slid after letting go)."""
    env = TestEnv("human", "human", map_name="grand", time_scale=stepping.TIME_SCALE)
    env.reset()
    env.timer.limit = 0
    a, b = env.players
    a.x, a.y = 115, 340
    b.dies()
    for _ in range(15):
        env.step()
    top = 0
    for _ in range(ticks):
        env.step([buttons, None])
        top = max(top, a.x_v * env.time_scale * 30)
    x = a.x
    for _ in range(60):
        env.step()
    return top, a.x - x


def test_running_on_a_platform_is_quick_and_stops_short():
    top, slide = sprint(RIGHT)
    assert top > 180       # (it was under 50 px/s: the ground gripped like glue)
    assert slide < 2.5 * 20  # let go, and you stop within about a ball's width


def test_heavy_is_way_slower():
    light, _ = sprint(RIGHT)
    heavy, _ = sprint(HEAVY_RIGHT)
    assert heavy < light / 4


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
