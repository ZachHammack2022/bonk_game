"""Jump buffering and coyote time on the jump maps (issue #7)."""
import pytest

from bonk_game.envs.utils.maps import make_map
from bonk_game.envs.utils.player import COYOTE_TIME, JUMP_BUFFER
from physics_helpers import tick


def setup(map_name="platform"):
    m = make_map(map_name)
    p, _ = m.make_players()
    p.x, p.y, p.x_v, p.y_v = 340, m.TOP - p.r - 1, 0, 0
    return m, p


def step(m, p, up=False):
    if up:
        p.move_up(2)
    tick(m, [p])


def settle(m, p):
    for _ in range(5):
        step(m, p)
    assert p.grounded


def test_grounded_jump_is_immediate():
    m, p = setup()
    settle(m, p)
    step(m, p, up=True)
    assert p.y_v < -p.jump_speed / 2


def test_tap_and_hold_jump_the_same_height():
    def peak(hold):
        m, p = setup()
        settle(m, p)
        y0 = best = p.y
        for t in range(60):
            step(m, p, up=hold or t == 0)
            best = min(best, p.y)
        return y0 - best

    # (Holding, the next jump goes the moment you land, mid-step: within a
    # pixel or two of the same height)
    assert peak(False) == pytest.approx(peak(True), abs=2)


@pytest.mark.parametrize("early", range(1, JUMP_BUFFER + 1))
def test_up_just_before_landing_jumps_on_landing(early):
    m, p = setup()
    settle(m, p)
    step(m, p, up=True)  # jump, then wait to come back down
    landed = None
    for t in range(80):
        step(m, p)
        if p.grounded and p.y_v > -p.jump_speed / 2:
            landed = t
            break
    assert landed is not None
    # Replay the same jump, pressing up `early` steps before landing
    m, p = setup()
    settle(m, p)
    step(m, p, up=True)
    for t in range(landed + 1):
        step(m, p, up=(t == landed - early + 1))
    step(m, p)
    assert p.y_v < -p.jump_speed / 2, "buffered jump should fire on landing"


def test_press_too_early_is_forgotten():
    m, p = setup()
    p.y -= 150  # high up, a long way to fall
    p.jump_buffer = 0
    step(m, p, up=True)
    for _ in range(80):
        step(m, p)
        if p.grounded:
            break
    assert p.grounded
    step(m, p)
    assert p.y_v > -p.jump_speed / 2  # at most a small landing bounce


def walk_off(m, p):
    """Roll off the right end of the platform; return steps since it left."""
    p.x = m.RIGHT - 2
    p.x_v = 6
    for _ in range(30):
        step(m, p)
        if not p.grounded:
            return
    raise AssertionError("never left the platform")


@pytest.mark.parametrize("late", range(COYOTE_TIME))
def test_coyote_jump_after_leaving_the_edge(late):
    m, p = setup()
    settle(m, p)
    walk_off(m, p)
    for _ in range(late):
        step(m, p)
    step(m, p, up=True)
    assert p.y_v < -p.jump_speed / 2


def test_no_jump_long_after_leaving_the_edge():
    m, p = setup()
    settle(m, p)
    walk_off(m, p)
    for _ in range(COYOTE_TIME + 2):
        step(m, p)
    y_v = p.y_v
    step(m, p, up=True)
    assert p.y_v > 0 and p.y_v >= y_v


def test_no_double_jump():
    m, p = setup()
    settle(m, p)
    step(m, p, up=True)
    for _ in range(COYOTE_TIME):
        step(m, p)
    y_v = p.y_v
    step(m, p, up=True)
    assert p.y_v > y_v  # gravity only, no second jump


def test_agent_actions_use_the_same_jump():
    from bonk_game.envs.utils import arena
    up = next(a for a, (dx, dy, h) in arena.ACTIONS.items() if dy < 0)
    m, p = setup()
    settle(m, p)
    step(m, p)
    arena.apply_action(p, up)
    assert p.y_v < -p.jump_speed / 2
