"""Draws the game world (maps, players, effects) in the game's visual style.

Everything here takes world coordinates (the 680x480 physics space) and
converts them using a scale and offset, so the same code draws the full
size game, menu thumbnails and the training env's debug window.
"""
import math
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame
import pygame.gfxdraw

from bonk_game.ui import theme
from bonk_game.ui.theme import darken, lighten, mix

_backgrounds = {}
_edge_glows = {}


def _gradient(size):
    if size not in _backgrounds:
        w, h = size
        surf = pygame.Surface(size)
        for y in range(h):
            pygame.draw.line(surf, mix(theme.BG_TOP, theme.BG_BOTTOM, y / max(1, h - 1)), (0, y), (w, y))
        # Soft light from the top centre: a small smooth radial gradient,
        # scaled up so there are no visible rings
        n = 64
        glow = pygame.Surface((n, n), pygame.SRCALPHA)
        glow.fill((255, 255, 255, 0))
        alpha = pygame.surfarray.pixels_alpha(glow)
        for gx in range(n):
            for gy in range(n):
                d = math.hypot((gx - n / 2) / (n / 2), (gy - n * 0.3) / (n / 2))
                alpha[gx, gy] = int(28 * max(0.0, 1 - d) ** 2)
        del alpha
        surf.blit(pygame.transform.smoothscale(glow, size), (0, 0))
        _backgrounds[size] = surf.convert() if pygame.display.get_init() and pygame.display.get_surface() else surf
    return _backgrounds[size]


def _edge_glow(size, thickness):
    """Red glow fading in from the left, right and bottom edges."""
    key = (size, thickness)
    if key not in _edge_glows:
        w, h = size
        k = 4  # build small, then smooth-scale up
        sw, sh = max(2, w // k), max(2, h // k)
        t = max(1.0, thickness / k)
        small = pygame.Surface((sw, sh), pygame.SRCALPHA)
        small.fill((*theme.DANGER, 0))
        alpha = pygame.surfarray.pixels_alpha(small)
        for x in range(sw):
            ex = max(0.0, 1 - min(x, sw - 1 - x) / t)
            for y in range(sh):
                ey = max(0.0, 1 - (sh - 1 - y) / t)
                alpha[x, y] = int(60 * max(ex, ey) ** 2)
        del alpha
        _edge_glows[key] = pygame.transform.smoothscale(small, size)
    return _edge_glows[key]


def block_point(block, u, v):
    """World point at (u, v) in an OrientedBlock's own frame, as fractions
    of its width and height from the centre."""
    wx, wy = block.to_world(u * block.w, v * block.h)
    return block.cx + wx, block.cy + wy


def oriented_face(block, lip):
    """Corners of an OrientedBlock's face: the block minus `lip` at the bottom."""
    hw, hh = block.w / 2, block.h / 2
    pts = []
    for x, y in ((-hw, -hh), (hw, -hh), (hw, hh - lip), (-hw, hh - lip)):
        wx, wy = block.to_world(x, y)
        pts.append((block.cx + wx, block.cy + wy))
    return pts


class Painter:
    def __init__(self, surface, scale=1.0, offset=(0, 0)):
        self.surface = surface
        self.scale = scale
        self.ox, self.oy = offset

    # --- coordinate helpers ---------------------------------------------
    def pt(self, x, y):
        return (round(self.ox + x * self.scale), round(self.oy + y * self.scale))

    def ln(self, v):
        return max(1, round(v * self.scale))

    def rect(self, x1, y1, x2, y2):
        a, b = self.pt(x1, y1)
        c, d = self.pt(x2, y2)
        return pygame.Rect(a, b, max(1, c - a), max(1, d - b))

    # --- primitives -----------------------------------------------------
    def circle(self, x, y, r, color):
        """Anti-aliased filled circle in screen pixels."""
        x, y, r = int(x), int(y), max(1, int(r))
        pygame.gfxdraw.filled_circle(self.surface, x, y, r, color)
        pygame.gfxdraw.aacircle(self.surface, x, y, r, color)

    def world_circle(self, x, y, r, color):
        sx, sy = self.pt(x, y)
        self.circle(sx, sy, r * self.scale, color)

    def line(self, p1, p2, color, width):
        pygame.draw.line(self.surface, color, self.pt(*p1), self.pt(*p2), self.ln(width))

    # --- scenery ---------------------------------------------------------
    def background(self):
        self.surface.blit(_gradient(self.surface.get_size()), (0, 0))

    def danger_edges(self):
        """Red glow on the screen edges you die past (open maps)."""
        self.surface.blit(_edge_glow(self.surface.get_size(), self.ln(16)), (0, 0))

    def block(self, x1, y1, x2, y2, color, kind="solid"):
        """A rounded, shaded slab. kind: solid, hazard, pad or wood."""
        r = self.rect(x1, y1, x2, y2)
        rad = max(0, min(self.ln(5), r.h // 2, r.w // 2))
        lip = min(self.ln(3), r.h // 3)

        shadow = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 60), shadow.get_rect(), border_radius=rad)
        self.surface.blit(shadow, (r.x, r.y + self.ln(4)))

        pygame.draw.rect(self.surface, darken(color, 0.28), r, border_radius=rad)
        pygame.draw.rect(self.surface, color, pygame.Rect(r.x, r.y, r.w, r.h - lip), border_radius=rad)

        old_clip = self.surface.get_clip()
        self.surface.set_clip(r)
        if kind == "hazard":
            step = self.ln(12)
            stripe = darken(color, 0.18)
            for sx in range(r.x - r.h, r.right + r.h, step * 2):
                pygame.draw.polygon(self.surface, stripe, [
                    (sx, r.bottom), (sx + step, r.bottom), (sx + step + r.h, r.y), (sx + r.h, r.y)])
        elif kind == "pad":
            chev = darken(color, 0.25)
            size = max(2, min(r.h // 2, self.ln(5)))
            cy = r.centery
            for cx in range(r.x + size * 2, r.right - size, size * 4):
                pygame.draw.lines(self.surface, chev, False,
                                  [(cx - size, cy + size // 2), (cx, cy - size // 2), (cx + size, cy + size // 2)],
                                  max(1, self.ln(2)))
        self.surface.set_clip(old_clip)

        if r.w > 2 * rad + 2 and r.h > 4:
            pygame.draw.line(self.surface, lighten(color, 0.4),
                             (r.x + rad, r.y + 1), (r.right - rad - 1, r.y + 1), max(1, self.ln(1.5)))

    def draw_block(self, block):
        """Draw a bodies.Block (or OrientedBlock / Bumper), styled by what it does."""
        kind = "hazard" if block.kill else "pad" if block.launch is not None else "solid"
        color = theme.HAZARD if block.kill else block.color
        if hasattr(block, "radius"):
            self.bumper(block.cx, block.cy, block.radius, color, kind)
        elif hasattr(block, "angle"):
            self.oriented_block(block, color, kind)
        else:
            self.block(block.x1, block.y1, block.x2, block.y2, color, kind)

    def oriented_block(self, block, color, kind="solid"):
        """A rotated slab: shadow, darker underside, face and a lit top edge."""
        pts = [self.pt(x, y) for x, y in block.corners()]
        drop = self.ln(4)
        xs, ys = zip(*pts)
        pad = drop + 2
        box = pygame.Rect(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
        shadow = pygame.Surface(box.size, pygame.SRCALPHA)
        pygame.draw.polygon(shadow, (0, 0, 0, 60), [(x - box.x, y - box.y + drop) for x, y in pts])
        self.surface.blit(shadow, box.topleft)

        pygame.draw.polygon(self.surface, darken(color, 0.28), pts)
        # Face: the same shape pulled in a little from the bottom edge
        lip = min(3, block.h / 3)
        inset = oriented_face(block, lip)
        face = [self.pt(x, y) for x, y in inset]
        pygame.draw.polygon(self.surface, color, face)
        if kind == "hazard":
            pygame.draw.polygon(self.surface, darken(color, 0.18), face, max(1, self.ln(2)))
        elif kind == "pad":
            a, b = self.pt(*block_point(block, -0.3, 0)), self.pt(*block_point(block, 0.3, 0))
            pygame.draw.line(self.surface, darken(color, 0.25), a, b, max(1, self.ln(2)))
        pygame.draw.aalines(self.surface, color, True, pts)
        top_a, top_b = face[0], face[1]
        pygame.draw.line(self.surface, lighten(color, 0.4), top_a, top_b, max(1, self.ln(1.5)))

    def bumper(self, x, y, r, color, kind="solid"):
        """A round piece; launch bumpers get a bright ring."""
        sx, sy = self.pt(x, y)
        sr = r * self.scale
        shadow = pygame.Surface((int(sr * 2.4), int(sr * 2.4)), pygame.SRCALPHA)
        pygame.draw.circle(shadow, (0, 0, 0, 60), (int(sr * 1.2), int(sr * 1.2)), int(sr))
        self.surface.blit(shadow, (sx - int(sr * 1.2), sy - int(sr * 1.2) + self.ln(4)))
        self.circle(sx, sy, sr, darken(color, 0.28))
        self.circle(sx, sy - self.ln(1.5), sr - self.ln(1.5), color)
        if kind == "pad":
            self.circle(sx, sy - self.ln(1.5), sr * 0.62, darken(color, 0.22))
            self.circle(sx, sy - self.ln(1.5), sr * 0.42, color)
        elif kind == "hazard":
            self.circle(sx, sy - self.ln(1.5), sr * 0.5, darken(color, 0.2))
        self.circle(sx - sr * 0.35, sy - sr * 0.4, max(1, sr * 0.2), lighten(color, 0.5))

    def swing(self, swing):
        sx, sy = swing.seat_pos()
        half = swing.seat_width / 2
        for end_x in (sx - half + 2, sx + half - 2):
            self.line((swing.px, swing.py), (end_x, sy - swing.lip_height), theme.ROPE, 2.5)
        for x1, y1, x2, y2 in swing.rects():
            self.block(x1, y1, x2, y2, theme.WOOD, "wood")
        px, py = self.pt(swing.px, swing.py)
        self.circle(px, py, self.ln(6), darken(theme.ROPE, 0.3))
        self.circle(px, py, self.ln(3), lighten(theme.ROPE, 0.3))

    def rail(self, x1, x2, y):
        a = self.pt(x1, y)
        b = self.pt(x2, y)
        w = self.ln(3)
        pygame.draw.line(self.surface, darken(theme.RAIL, 0.3), a, b, w + 2)
        pygame.draw.line(self.surface, theme.RAIL, a, b, w)
        for x in (a[0], b[0]):
            self.circle(x, a[1], self.ln(5), theme.RAIL)
            self.circle(x, a[1], self.ln(2), darken(theme.RAIL, 0.4))

    def closing_walls(self, walls, world_w, world_h, t=0.0):
        """Sudden-death walls: red zones from the screen edges in to x=walls."""
        if walls is None:
            return
        left, right = walls
        pulse = 0.5 + 0.5 * math.sin(t * 8)
        zone = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        fill = (*theme.DANGER, int(70 + 30 * pulse))
        for x1, x2 in ((-40, left), (right, world_w + 40)):
            if x2 > x1:
                zone.fill(fill, self.rect(x1, -40, x2, world_h + 40))
        self.surface.blit(zone, (0, 0))
        glow = lighten(theme.DANGER, 0.25 + 0.25 * pulse)
        for x in (left, right):
            self.line((x, -40), (x, world_h + 40), glow, 3)

    # --- actors -------------------------------------------------------------
    def player(self, p, color=None):
        color = color or p.color
        x, y = self.pt(p.x, p.y)
        r = p.r * self.scale
        heavy = 0.0
        if p.max_m > p.min_m:
            heavy = max(0.0, min(1.0, (p.m - p.min_m) / (p.max_m - p.min_m)))

        # Soft drop shadow
        shadow = pygame.Surface((int(r * 2.4), int(r * 2.4)), pygame.SRCALPHA)
        pygame.draw.circle(shadow, (0, 0, 0, 55), (int(r * 1.2), int(r * 1.2)), int(r))
        self.surface.blit(shadow, (x - int(r * 1.2), y - int(r * 1.2) + self.ln(4)))

        # Heavy players get a thick dark rim and a deeper colour
        rim = darken(color, 0.5)
        fill = mix(color, darken(color, 0.3), heavy)
        rim_w = self.ln(2.5) + heavy * r * 0.35
        self.circle(x, y, r, rim)
        self.circle(x, y, r - rim_w, fill)
        # Shine
        self.circle(x - r * 0.32, y - r * 0.34, max(1, r * 0.22), lighten(fill, 0.55))

    def offscreen_marker(self, p, world_w):
        """Arrow on the top edge pointing at a player who is above the screen."""
        if p.y + p.r >= 0:
            return
        x = min(max(p.x, 14), world_w - 14)
        tip = self.pt(x, 4)
        s = self.ln(9)
        pygame.draw.polygon(self.surface, p.color, [tip, (tip[0] - s, tip[1] + s * 1.4), (tip[0] + s, tip[1] + s * 1.4)])
        pygame.draw.polygon(self.surface, darken(p.color, 0.5),
                            [tip, (tip[0] - s, tip[1] + s * 1.4), (tip[0] + s, tip[1] + s * 1.4)], max(1, self.ln(1.5)))
