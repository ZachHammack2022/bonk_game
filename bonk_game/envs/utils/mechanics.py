"""This file includes all physics based functions to direct gameplay."""
import math

BOUNCE = -0.8  # fraction of vertical speed kept (and flipped) on a floor/ceiling hit


def env_collision_game(agent, platform) -> bool:
    """Handle an agent hitting a platform in the playable game.

    A kill platform respawns the agent and returns True so the caller can
    award a point to the opponent. Any other platform bounces the agent.
    """
    if env_collision(agent, platform):
        if platform.kill:
            agent.reset()
            return True
        handle_env_collision(agent, platform)
    return False


def env_collision_gym(agent, platform) -> None:
    """Handle an agent hitting a platform in the training env.

    A kill platform marks the agent dead (ending the episode). Any other
    platform bounces the agent.
    """
    if env_collision(agent, platform):
        if platform.kill:
            agent.dies()
        else:
            handle_env_collision(agent, platform)


def env_collision(agent, platform) -> bool:
    """Return True if the circular agent overlaps the rectangular platform."""
    cx, cy, radius = agent.x, agent.y, agent.r
    rx, ry = min(platform.x1, platform.x2), min(platform.y1, platform.y2)
    rw, rh = abs(platform.x2 - platform.x1), abs(platform.y2 - platform.y1)

    # Closest point on the rectangle to the circle's centre
    test_x = min(max(cx, rx), rx + rw)
    test_y = min(max(cy, ry), ry + rh)

    return math.hypot(cx - test_x, cy - test_y) <= radius


def handle_env_collision(agent, platform) -> None:
    """Bounce the agent off a horizontal platform (floor or ceiling).

    The agent is pushed back out of the platform on whichever side its
    centre is on, so this works for any horizontal platform rather than only
    the default floor and ceiling.
    """
    agent.y_a = 0
    agent.y_v = BOUNCE * agent.y_v
    top, bottom = min(platform.y1, platform.y2), max(platform.y1, platform.y2)
    if agent.y < (top + bottom) / 2:
        # Agent is above the platform: rest on top of it
        agent.y = top - agent.r - 1
    else:
        # Agent is below the platform: push down beneath it
        agent.y = bottom + agent.r + 0.01


def player_collision(a1, a2) -> None:
    """Bounce two agents off each other if they overlap."""
    d = math.hypot(a1.x - a2.x, a1.y - a2.y)
    if d < (a1.r + a2.r):
        handle_player_collision(a1, a2, d)


def handle_player_collision(a1, a2, d) -> None:
    """Elastic collision between two circles of different masses.

    Also separates the circles so they don't stay overlapping and "stick"
    together over several frames. Heavier players get pushed less.
    """
    if d == 0:
        # Perfectly stacked: pick an arbitrary axis to separate along
        nx, ny, d = 1.0, 0.0, 1e-6
    else:
        nx = (a2.x - a1.x) / d
        ny = (a2.y - a1.y) / d

    # Only exchange momentum if they're moving towards each other; otherwise
    # two overlapping players that are already separating get pulled back in.
    rel_v = (a1.x_v - a2.x_v) * nx + (a1.y_v - a2.y_v) * ny
    if rel_v > 0:
        p = 2 * rel_v / (a1.m + a2.m)
        a1.x_v -= p * a2.m * nx
        a1.y_v -= p * a2.m * ny
        a2.x_v += p * a1.m * nx
        a2.y_v += p * a1.m * ny

    # Push apart in proportion to the other player's share of the mass
    overlap = (a1.r + a2.r) - d
    total = a1.m + a2.m
    a1.x -= nx * overlap * (a2.m / total)
    a1.y -= ny * overlap * (a2.m / total)
    a2.x += nx * overlap * (a1.m / total)
    a2.y += ny * overlap * (a1.m / total)
