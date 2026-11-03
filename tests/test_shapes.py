"""Rotated rectangles and round bumpers (issue #9)."""
import math

import pytest

from bonk_game.envs.utils.bodies import Block, Bumper, OrientedBlock, collide_block
from bonk_game.envs.utils.maps import make_map
from bonk_game.envs.utils.player import player


def ball(x, y, vx=0.0, vy=0.0):
    p = player(20, 0, 680, 0, 480, (255, 0, 0), clamp_bottom=False)
    p.x, p.y, p.x_v, p.y_v = x, y, vx, vy
    p.can_fly = False
    return p


def test_unrotated_oriented_block_matches_block():
    """At 0 degrees it must behave exactly like the plain Block."""
    for x, y, vx, vy in [(300, 285, 0, 6), (250, 300, 5, 1), (390, 330, -4, -2), (300, 340, 0, -7)]:
        a, b = ball(x, y, vx, vy), ball(x, y, vx, vy)
        collide_block(a, Block(240, 300, 380, 320, None, restitution=0.4, friction=0.1))
        collide_block(b, OrientedBlock(310, 310, 140, 20, 0, None, restitution=0.4, friction=0.1))
        assert (a.x, a.y, a.x_v, a.y_v) == pytest.approx((b.x, b.y, b.x_v, b.y_v))


def test_slope_normal_points_out_of_its_top():
    slope = OrientedBlock(340, 300, 200, 16, 30, None)  # rises to the left
    p = ball(340, 300 - 8 - 19)
    nx, ny, depth = slope.contact(p, 0, 0)
    assert (nx, ny) == pytest.approx((math.sin(math.radians(30)), -math.cos(math.radians(30))))
    assert depth > 0


def test_ball_rolls_down_a_slope():
    slope = OrientedBlock(340, 300, 300, 16, 20, None, restitution=0.0)
    nx, ny = slope.up
    p = ball(340 + nx * 29, 300 + ny * 29)  # resting on top
    for _ in range(30):
        collide_block(p, slope)
        p.update()
    assert p.x > 360  # slid down to the right
    assert p.grounded or p.y_v > 0


def test_ball_lands_on_a_slope_and_can_jump():
    slope = OrientedBlock(340, 300, 300, 16, 25, None, restitution=0.0)
    p = ball(340, 200)
    p.jump_speed = 20
    for _ in range(40):
        p.grounded = False
        collide_block(p, slope)
        p.update()
        if p.grounded:
            break
    assert p.grounded


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
    p = ball(340 + nx * 24, 300 + ny * 24, 0, 3)
    collide_block(p, pad)
    assert p.x_v * nx + p.y_v * ny == pytest.approx(20)
    assert p.x_v < 0 and p.y_v < 0  # up and to the left


def test_flat_launch_pad_unchanged():
    pad = Block(300, 400, 380, 410, None, restitution=0.0, launch=25)
    p = ball(340, 381, 2, 4)
    collide_block(p, pad)
    assert p.y_v == -25 and p.x_v == 2


def test_bumper_pushes_out_and_bounces():
    b = Bumper(340, 300, 20, None, restitution=0.8)
    p = ball(340 - 35, 300, 6, 0)
    collide_block(p, b)
    assert math.hypot(p.x - 340, p.y - 300) == pytest.approx(40)
    assert p.x_v < 0


def test_launch_bumper_fires_away_from_its_centre():
    b = Bumper(340, 300, 20, None, launch=15)
    p = ball(340 + 25, 300 - 25, 0, 0)
    collide_block(p, b)
    assert p.x_v > 0 and p.y_v < 0
    assert math.hypot(p.x_v, p.y_v) == pytest.approx(15, abs=0.5)


def test_kill_bumper_kills():
    assert collide_block(ball(340, 270), Bumper(340, 300, 20, None, kill=True))
    assert not collide_block(ball(340, 200), Bumper(340, 300, 20, None, kill=True))


def test_pieces_move_with_a_sliding_platform():
    m = make_map("slider")
    post = m.platform.blocks[1]
    assert isinstance(post, OrientedBlock)
    x = post.cx
    m.platform.vx = 5
    m.step()
    assert post.cx == pytest.approx(x + 5 * m.platform.damping)


def test_slider_posts_lean_outward():
    m = make_map("slider")
    left, right = m.platform.blocks[1], m.platform.blocks[2]
    assert left.angle < 0 < right.angle
