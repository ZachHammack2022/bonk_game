"""Smooth drawing between physics steps.

Physics runs at 30 steps per second (what agents were trained on), and the
window draws at 60 fps. Drawing the latest physics state on every frame
shows each position twice, which looks steppy. Instead, each frame draws
the world blended between the previous and the latest physics step,
according to how far we are into the next step.

Only drawing changes: the blended values are put on the objects just for
the draw call, then the exact physics values are put back.
"""
from contextlib import contextmanager

# A value that changes more than this in one step was teleported (a
# respawn), not moved; it's drawn where it is rather than blended.
MAX_JUMP = 60


def _targets(env):
    """(object, attribute) pairs of everything that moves on screen."""
    out = []
    for p in env.players:
        out += [(p, "x"), (p, "y")]
    m = env.map
    blocks = list(getattr(m, "blocks", []))
    for body in getattr(m, "bodies", []):
        blocks += getattr(body, "blocks", [])
        if hasattr(body, "theta"):
            out.append((body, "theta"))
    for b in blocks:
        out += [(b, a) for a in ("x1", "y1", "x2", "y2")]
    return out


class Interpolator:
    def __init__(self, env):
        self.env = env
        self.prev = None

    def capture(self):
        return [(obj, attr, getattr(obj, attr)) for obj, attr in _targets(self.env)]

    def before_step(self):
        self.prev = self.capture()

    def forget(self):
        """Draw the current state as is until the next step (after a reset)."""
        self.prev = None

    @contextmanager
    def blended(self, alpha):
        """While inside, the world is at prev + (current - prev) * alpha."""
        cur = self.capture()
        prev = self.prev
        if (prev is None or alpha >= 1 or len(prev) != len(cur)
                or any(a[0] is not b[0] or a[1] != b[1] for a, b in zip(prev, cur))):
            # Nothing to blend from, or the level was rebuilt (new round)
            yield
            return
        alpha = max(0.0, alpha)
        try:
            for (obj, attr, now), (_, _, before) in zip(cur, prev):
                if abs(now - before) < MAX_JUMP:
                    setattr(obj, attr, before + (now - before) * alpha)
            yield
        finally:
            for obj, attr, now in cur:
                setattr(obj, attr, now)
