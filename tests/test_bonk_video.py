"""Our physics still matches the bonk.io recording (bench/bonk_video)."""
from bench.bonk_video import compare
from bonk_game.envs.utils import world


def test_the_swing_swings_freely_at_the_recordings_period():
    d, _ = compare.load()
    swing = compare.our_swing(20, 40)
    assert abs(compare.our_period(swing) - compare.recorded_period(d)) < 0.5  # s (7.35 vs 7.2)
    # A push keeps it going back and forth on its own, slowly losing height
    assert sum(1 for a, b in zip(swing, swing[1:]) if a * b < 0) >= 10
    assert compare.furthest(swing, 16, 20) > 10
    assert compare.furthest(swing, 36, 40) < compare.furthest(swing, 6, 10)


def test_an_empty_seat_settles_in_the_middle():
    from bonk_game.envs.utils.maps import make_map
    from bonk_game.envs.utils import stepping
    import math
    m = make_map("swing")
    p, q = m.make_players()
    p.dies()
    q.dies()
    m.steps = -10 ** 6
    m.swing.theta = 0.4
    for _ in range(30 * 60):
        m.step(move=False)
        stepping.advance([], m, time_scale=stepping.TIME_SCALE)
    assert abs(math.degrees(m.swing.theta)) < 2.5


def test_gravity_and_the_falling_floor_are_the_recordings():
    d, scale = compare.load()
    g = world.GRAVITY * compare.STEPS_PER_SECOND ** 2
    # (the recorded fall may have had "down" held a little: it's an upper bound)
    assert 0.85 * compare.recorded_gravity(d, scale) < g <= compare.recorded_gravity(d, scale)
    from bonk_game.envs.utils.maps import SwingMap
    sink = SwingMap.SINK_SPEED * compare.STEPS_PER_SECOND
    assert abs(sink - compare.recorded_sink(d, scale)) < 0.5
