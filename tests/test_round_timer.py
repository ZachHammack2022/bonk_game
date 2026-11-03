"""Round timer and sudden death (issue #6)."""
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils import arena
from bonk_game.envs.utils.maps import MAPS
from bonk_game.envs.utils.timer import STEPS_PER_SECOND, WALL_SPEED, RoundTimer


class Idle:
    """A model that always picks action 0."""

    def predict(self, obs, *args, **kwargs):
        return 0, None


def test_timer_counts_down_then_walls_close():
    t = RoundTimer(2, start=(100, 500))
    assert t.remaining == 2 and t.walls() is None
    for _ in range(2 * STEPS_PER_SECOND - 1):
        t.step()
    assert not t.sudden_death and t.walls() is None
    t.step()
    assert t.sudden_death and t.remaining == 0
    assert t.walls() == (100, 500)
    for _ in range(10):
        t.step()
    assert t.walls() == pytest.approx((100 + 10 * WALL_SPEED, 500 - 10 * WALL_SPEED))
    # They meet in the middle and stop there
    for _ in range(1000):
        t.step()
    assert t.walls() == (300, 300)


def test_disabled_timer_never_triggers():
    t = RoundTimer(0)
    for _ in range(10_000):
        t.step()
    assert not t.enabled and t.remaining is None and t.walls() is None


def test_walls_kill_players_outside():
    class P:
        x = 0

    t = RoundTimer(1, start=(0, 680))
    for _ in range(STEPS_PER_SECOND + 50):
        t.step()
    left, right = t.walls()
    p = P()
    p.x = left - 1
    assert t.kills(p)
    p.x = (left + right) / 2
    assert not t.kills(p)
    p.x = right + 1
    assert t.kills(p)


@pytest.mark.parametrize("map_name", list(MAPS))
def test_stalled_round_always_ends(map_name):
    """Two players that never fight still finish the round."""
    env = TestEnv(Idle(), Idle(), map_name=map_name, round_time=1, winning_score=1)
    env.reset()
    # Worst case: timer, then the walls crossing half the screen
    limit = STEPS_PER_SECOND + int(env.map.width / 2 / WALL_SPEED) + 5
    for _ in range(limit):
        _, done, _ = env.step([0, 0])
        if done or env.timer.steps == 0:
            break
    assert max(env.scores) >= 1


def test_timer_resets_each_round():
    env = TestEnv(Idle(), Idle(), map_name="platform", round_time=1)
    env.reset()
    for _ in range(10):
        env.step([0, 0])
    assert env.timer.steps == 10
    env.new_round()
    assert env.timer.steps == 0


def test_classic_timer_restarts_after_a_point():
    env = TestEnv(Idle(), Idle(), map_name="classic", round_time=5)
    env.reset()
    env.timer.steps = 20
    env.p1.x = arena.LEFT  # into the deadly wall
    env.check_collisions()
    assert env.p2.score == 1
    assert env.timer.steps == 0


def test_round_time_override():
    assert TestEnv(Idle(), Idle(), map_name="swing").timer.limit == MAPS["swing"].round_time * STEPS_PER_SECOND
    assert not TestEnv(Idle(), Idle(), map_name="swing", round_time=0).timer.enabled
