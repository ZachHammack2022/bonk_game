"""Rotated rectangles and round bumpers (issue #9), in the Box2D world."""
import math

import pytest

from bonk_game.envs.utils.bodies import Block, Bumper, OrientedBlock
from bonk_game.envs.utils.maps import make_map
from bonk_game.envs.utils.player import player
from bonk_game.envs.utils.world import LIFT, World


def ball(x, y, vx=0.0, vy=0.0):
    p = player(20, 0, 680, 0, 480, (255, 0, 0), clamp_bottom=False)
    p.x, p.y, p.x_v, p.y_v = x, y, vx, vy
    p.can_fly = False
    p.v_range = 40
    return p


def run(pieces, p, steps=1):
    w = World(pieces)
    for _ in range(steps):
        w.step([p])
    return w


def test_unrotated_oriented_block_matches_block():
    """At 0 degrees it must behave exactly like the plain Block."""
    for x, y, vx, vy in [(300, 275, 0, 6), (250, 270, 5, 1), (390, 345, -4, -2), (300, 345, 0, -7)]:
        a, b = ball(x, y, vx, vy), ball(x, y, vx, vy)
        run([Block(240, 300, 380, 320, None, restitution=0.4, friction=0.1)], a, 3)
        run([OrientedBlock(310, 310, 140, 20, 0, None, restitution=0.4, friction=0.1)], b, 3)
        assert (a.x, a.y, a.x_v, a.y_v) == pytest.approx((b.x, b.y, b.x_v, b.y_v), abs=1e-3)


def test_slope_normal_points_out_of_its_top():
    slope = OrientedBlock(340, 300, 200, 16, 30, None)  # rises to the left
    assert slope.up == pytest.approx((math.sin(math.radians(30)), -math.cos(math.radians(30))))
    p = ball(340 + slope.up[0] * 27.9, 300 + slope.up[1] * 27.9)
    w = run([slope], p)
    [(_, n, _)] = list(w.ball(p).touching())
    assert n == pytest.approx(slope.up, abs=1e-3)
    assert p.grounded


def test_ball_rolls_down_a_slope():
    slope = OrientedBlock(340, 300, 300, 16, 20, None, restitution=0.0)
    nx, ny = slope.up
    p = ball(340 + nx * 29, 300 + ny * 29)  # resting on top
    run([slope], p, 30)
    assert p.x > 360  # slid down to the right
    assert p.grounded or p.y_v > 0


def test_ball_lands_on_a_slope_and_can_jump():
    slope = OrientedBlock(340, 300, 300, 16, 25, None, restitution=0.0)
    p = ball(340, 200)
    p.jump_speed = 20
    w = World([slope])
    for _ in range(40):
        w.step([p])
        if p.grounded:
            break
    assert p.grounded
    p.move_up(2)
    assert p.y_v == -20


def test_standing_post_has_its_foot_where_asked():
    post = OrientedBlock.standing(200, 300, 10, 40, -20, None)
    corners = post.corners()
    bottom_mid = ((corners[2][0] + corners[3][0]) / 2, (corners[2][1] + corners[3][1]) / 2)
    assert bottom_mid == pytest.approx((200, 300))
    top_mid = ((corners[0][0] + corners[1][0]) / 2, (corners[0][1] + corners[1][1]) / 2)
    assert top_mid[0] < 200  # leans left


def test_angled_launch_pad_fires_along_its_face():
    pad = OrientedBlock(340, 300, 200, 12, -30, None, launch=20)
    nx, ny = pad.up
    p = ball(340 + nx * 27, 300 + ny * 27, 0, 3)
    run([pad], p)
    assert p.x_v * nx + p.y_v * ny == pytest.approx(20 * LIFT, abs=1.5)  # (world.LIFT)
    assert p.x_v < 0 and p.y_v < 0  # up and to the left


def test_flat_launch_pad_fires_straight_up():
    pad = Block(300, 400, 380, 410, None, restitution=0.0, launch=25)
    p = ball(340, 378, 2, 4)
    run([pad], p)
    assert p.y_v == pytest.approx(-25 * LIFT, abs=1.5)
    assert p.x_v == pytest.approx(2, abs=0.1)


def test_bumper_bounces():
    b = Bumper(340, 300, 20, None, restitution=0.8)
    p = ball(340 - 45, 300, 6, 0)
    p.gravity = 0
    run([b], p, 3)
    assert math.hypot(p.x - 340, p.y - 300) >= 39.5
    assert p.x_v < -3


def test_launch_bumper_fires_away_from_its_centre():
    b = Bumper(340, 300, 20, None, launch=15)
    p = ball(340 + 28, 300 - 28, 0, 0)
    p.gravity = 0
    run([b], p)
    assert p.x_v > 0 and p.y_v < 0
    assert math.hypot(p.x_v, p.y_v) == pytest.approx(15 * LIFT, abs=1)


def test_kill_bumper_kills():
    near, far = ball(340, 262), ball(340, 200)
    run([Bumper(340, 300, 20, None, kill=True)], near)
    run([Bumper(340, 300, 20, None, kill=True)], far)
    assert near.doomed and not far.doomed


def test_pieces_move_with_a_sliding_platform():
    m = make_map("slider")
    post = m.platform.blocks[2]
    assert isinstance(post, OrientedBlock)
    x = post.cx
    m.platform.vx = 5
    m.step()
    assert post.cx == pytest.approx(x + 5, rel=0.05)  # (less what the pull home took off)
    assert post.cx - x == pytest.approx(m.platform.offset)


def test_slider_posts_lean_outward():
    m = make_map("slider")
    left, right = m.halves[0].blocks[2], m.halves[1].blocks[2]
    assert left.angle < 0 < right.angle
