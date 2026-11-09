"""Our physics still matches the bonk.io recording (bench/bonk_video)."""
from bench.bonk_video import compare
from bonk_game.envs.utils import world


def test_the_swing_comes_back_as_in_the_recording():
    rms, _ = compare.swing_error()
    assert rms < 1.0  # degrees of rope, over 3.5 s (0.24 when measured)


def test_gravity_and_the_falling_floor_are_the_recordings():
    d, scale = compare.load()
    g = world.GRAVITY * compare.STEPS_PER_SECOND ** 2
    # (the recorded fall may have had "down" held a little: it's an upper bound)
    assert 0.85 * compare.recorded_gravity(d, scale) < g <= compare.recorded_gravity(d, scale)
    from bonk_game.envs.utils.maps import SwingMap
    sink = SwingMap.SINK_SPEED * compare.STEPS_PER_SECOND
    assert abs(sink - compare.recorded_sink(d, scale)) < 0.5
