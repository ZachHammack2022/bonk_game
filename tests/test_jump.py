"""Jump buffering and coyote time on the jump maps (issue #7)."""
import pytest

from bonk_game.envs.utils import player as player_mod
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


def test_holding_up_hovers_higher_than_a_tap():
    def peak(hold):
        m, p = setup()
        settle(m, p)
        y0 = best = p.y
        for t in range(60):
            step(m, p, up=hold or t == 0)
            best = min(best, p.y)
        return y0 - best

    # Measured from bonk.io: a tap hops ~30 px; holding "up" hovers, for a
    # jump about four times as high (map.hover cancels most of gravity)
    tap, hold = peak(False), peak(True)
    assert 25 < tap < 45
    assert 90 < hold < 180


def test_hovering_slows_a_fall_but_never_lifts_you():
    m, p = setup()
    p.y, p.y_v, p.grounded = 100, 0, False
    for _ in range(10):
        step(m, p, up=True)
    assert p.y_v > 0  # still falling
    m, q = setup()
    q.y, q.y_v, q.grounded = 100, 0, False
    for _ in range(10):
        step(m, q)
    assert p.y_v < q.y_v / 3


def test_sideways_pushes_are_gentle():
    m, p = setup()
    p.x = 225  # (the platform's left end: room to run)
    assert p.push == pytest.approx(0.5)
    settle(m, p)
    x0 = p.x
    for _ in range(30):
        p.move_right(p.push)
        step(m, p)
    # Running, the ground grips lightly (world.GRIP_RUNNING): a second of
    # running from a stand covers ~150 px here (at full speed), at ~8 px a
    # step and still speeding up, where Classic's full-strength push would
    # go far further
    assert 110 < p.x - x0 < 200
    assert 6 < p.x_v < 11


@pytest.mark.parametrize("early", range(1, JUMP_BUFFER + 1))
def test_up_just_before_landing_jumps_on_landing(early):
    m, p = setup()
    p.hover = 0
    settle(m, p)
    step(m, p, up=True)  # jump, then wait to come back down
    landed = None
    for t in range(80):
        step(m, p)
        if p.grounded and p.y_v > -p.jump_speed / 2:
            landed = t
            break
    assert landed is not None
    # Replay the same jump, pressing up `early` steps before landing (no
    # hovering, so the press doesn't change when we land)
    m, p = setup()
    p.hover = 0
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
    assert p.y_v > -p.jump_speed * 0.6  # at most a landing bounce, not a jump


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


def test_players_bounce_off_each_other_a_little_softer_than_elastic():
    from bonk_game.envs.utils.world import PLAYER_BOUNCE, World
    m, a = setup()
    b = m.make_players()[1]
    a.x, a.y, a.x_v, a.y_v = 300, 200, 4, 0
    b.x, b.y, b.x_v, b.y_v = 341, 200, 0, 0
    for p in (a, b):
        p.gravity = 0
    World().step([a, b])
    # Separating speed is PLAYER_BOUNCE of the closing speed; momentum kept
    assert b.x_v - a.x_v == pytest.approx(PLAYER_BOUNCE * 4, abs=0.01)
    assert a.x_v + b.x_v == pytest.approx(4, abs=0.01)
    assert 0.7 <= PLAYER_BOUNCE < 1


def pogo_height(m, p, down_steps):
    """Jump, hold down for `down_steps` on the way down, then hold up through
    the landing: how high the bounce after it goes (px above the ground)."""
    settle(m, p)
    ground = p.y
    step(m, p, up=True)
    while p.y_v < 0:
        step(m, p)
    for _ in range(down_steps):
        p.move_down(p.push)
        step(m, p)
    for _ in range(40):  # up through the landing, until we're going up again
        step(m, p, up=True)
        if p.y_v < 0 and ground - p.y > 5:
            break
    top = p.y
    while p.y_v < 0:
        step(m, p)
        top = min(top, p.y)
    return ground - top


def test_a_pogo_bounces_higher_than_a_jump():
    m, p = setup()
    p.hover = 0
    settle(m, p)
    ground = p.y
    step(m, p, up=True)
    top = p.y
    while p.y_v < 0:
        step(m, p)
        top = min(top, p.y)
    jump = ground - top
    m, p = setup()
    p.hover = 0
    soft = pogo_height(m, p, 0)
    m, p = setup()
    p.hover = 0
    hard = pogo_height(m, p, 5)
    assert soft > jump * 1.5        # jumping as you land keeps some of the fall
    assert hard > soft             # coming down harder bounces higher
    assert hard > jump * 2


def test_a_standing_jump_is_unchanged(monkeypatch):
    def height():
        m, p = setup()
        settle(m, p)
        ground = p.y
        step(m, p, up=True)
        top = p.y
        while p.y_v < 0:
            step(m, p)
            top = min(top, p.y)
        return ground - top

    with_pogo = height()
    monkeypatch.setattr(player_mod, "POGO", 0.0)
    assert with_pogo == pytest.approx(height())  # (only a jump on landing pogos)
