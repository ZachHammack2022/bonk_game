"""The game: title screen, map select, player setup, matches and results.

Run with `python3 main.py`. Everything is drawn in a 680x480 "virtual"
space (the same as the physics world) and scaled up to fit the screen.
"""
import math
import os
import random

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils import arena
from bonk_game.envs.utils.maps import MAPS, make_map
from bonk_game.ui import theme
from bonk_game.ui.bot import Bot
from bonk_game.ui.interp import Interpolator
from bonk_game.ui.painter import Painter
from bonk_game.ui.sound import Sound

W, H = arena.WIDTH, arena.HEIGHT
FPS = 60
PHYSICS_HZ = 30  # the physics was tuned for 30 steps per second
FIRST_TO_OPTIONS = [3, 5, 7, 10, 25, 50, 100]
MAP_ORDER = ["platform", "slider", "swing", "classic"]
ARROWS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def ease_out_back(t):
    t = max(0.0, min(1.0, t))
    c = 1.70158
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


# ---------------------------------------------------------------------------
# Drawing helpers for UI in virtual coordinates
# ---------------------------------------------------------------------------
class UI:
    def __init__(self, surface, scale):
        self.surface = surface
        self.s = scale

    def v(self, n):
        return int(round(n * self.s))

    def rect(self, x, y, w, h):
        return pygame.Rect(self.v(x), self.v(y), self.v(w), self.v(h))

    def text(self, s, size, color, pos, anchor="center", bold=True, shadow=True, alpha=255, scale=1.0):
        font = theme.font(size * self.s, bold)
        surf = font.render(str(s), True, color)
        if scale != 1.0:
            surf = pygame.transform.smoothscale(
                surf, (max(1, int(surf.get_width() * scale)), max(1, int(surf.get_height() * scale))))
        if alpha < 255:
            surf.set_alpha(alpha)
        r = surf.get_rect(**{anchor: (self.v(pos[0]), self.v(pos[1]))})
        if shadow:
            sh = font.render(str(s), True, (0, 0, 0))
            if scale != 1.0:
                sh = pygame.transform.smoothscale(sh, surf.get_size())
            sh.set_alpha(int(90 * alpha / 255))
            self.surface.blit(sh, (r.x, r.y + self.v(2)))
        self.surface.blit(surf, r)
        return r

    def text_width(self, s, size, bold=True):
        return theme.font(size * self.s, bold).size(str(s))[0] / self.s

    def panel(self, rect, color=theme.PANEL, radius=14, border=theme.PANEL_BORDER, alpha=225, border_w=1.5):
        r = rect if isinstance(rect, pygame.Rect) else self.rect(*rect)
        rad = self.v(radius)
        surf = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(surf, (*color, alpha), surf.get_rect(), border_radius=rad)
        if border:
            pygame.draw.rect(surf, (*border, min(255, alpha + 20)), surf.get_rect(),
                             max(1, self.v(border_w)), border_radius=rad)
        self.surface.blit(surf, r)
        return r

    def dim(self, alpha):
        shade = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        shade.fill((10, 14, 24, int(alpha)))
        self.surface.blit(shade, (0, 0))

    def button(self, rect, label, focused=False, primary=False, size=17):
        x, y, w, h = rect
        lift = -2 if focused else 0
        base = theme.ACCENT if primary else theme.PANEL_LIGHT
        if focused and not primary:
            base = theme.lighten(theme.PANEL_LIGHT, 0.12)
        r = self.rect(x, y + lift, w, h)
        shadow = self.rect(x, y + 4, w, h)
        pygame.draw.rect(self.surface, theme.darken(base, 0.45), shadow, border_radius=self.v(12))
        pygame.draw.rect(self.surface, base, r, border_radius=self.v(12))
        if focused:
            pygame.draw.rect(self.surface, theme.TEXT if not primary else theme.lighten(theme.ACCENT, 0.6),
                             r, max(1, self.v(2)), border_radius=self.v(12))
        color = (40, 30, 10) if primary else theme.TEXT
        self.text(label, size, color, (x + w / 2, y + h / 2 + lift), shadow=not primary)

    def keycap_width(self, label, size=12, h=22):
        return h if label in ARROWS else max(h, self.text_width(label, size) + 12)

    def keycap(self, label, x, y, h=22, size=12):
        """A keyboard key. Arrow keys are "up", "down", "left", "right"."""
        w = self.keycap_width(label, size, h)
        r = self.rect(x, y, w, h)
        pygame.draw.rect(self.surface, theme.darken(theme.PANEL_LIGHT, 0.4), r.move(0, self.v(3)), border_radius=self.v(5))
        pygame.draw.rect(self.surface, theme.lighten(theme.PANEL_LIGHT, 0.15), r, border_radius=self.v(5))
        if label in ARROWS:
            self.arrow(x + w / 2, y + h / 2, ARROWS[label], h * 0.22, theme.TEXT)
        else:
            self.text(label, size, theme.TEXT, (x + w / 2, y + h / 2), shadow=False)
        return w

    def arrow(self, cx, cy, direction, size, color):
        """A filled triangle pointing in direction (dx, dy)."""
        dx, dy = direction
        px, py = -dy, dx
        pts = [(cx + dx * size, cy + dy * size),
               (cx - dx * size + px * size, cy - dy * size + py * size),
               (cx - dx * size - px * size, cy - dy * size - py * size)]
        pygame.draw.polygon(self.surface, color, [(self.v(a), self.v(b)) for a, b in pts])

    def chevron(self, cx, cy, direction, size, color, width=3):
        pts = [(cx - direction * size * 0.5, cy - size), (cx + direction * size * 0.5, cy),
               (cx - direction * size * 0.5, cy + size)]
        pygame.draw.lines(self.surface, color, False, [(self.v(a), self.v(b)) for a, b in pts], max(1, self.v(width)))

    def ball(self, x, y, r, color, heavy=0.0):
        p = Painter(self.surface, self.s)
        sx, sy = p.pt(x, y)
        rr = r * self.s
        p.circle(sx, sy + self.v(3), rr, (0, 0, 0, 60))
        p.circle(sx, sy, rr, theme.darken(color, 0.5))
        p.circle(sx, sy, rr - self.v(2.5) - heavy * rr * 0.35, theme.mix(color, theme.darken(color, 0.3), heavy))
        p.circle(sx - rr * 0.32, sy - rr * 0.34, max(1, rr * 0.22), theme.lighten(color, 0.55))

    def wrap(self, s, size, width, bold=False):
        words, lines, line = s.split(), [], ""
        for word in words:
            trial = (line + " " + word).strip()
            if self.text_width(trial, size, bold) > width and line:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        return lines


class Button:
    def __init__(self, label, rect, action, primary=False, size=17):
        self.label = label
        self.rect = rect
        self.action = action
        self.primary = primary
        self.size = size

    def contains(self, vx, vy):
        x, y, w, h = self.rect
        return x <= vx <= x + w and y <= vy <= y + h


class Menu:
    """A vertical list of buttons driven by keyboard or mouse."""

    def __init__(self, app, buttons, focus=0):
        self.app = app
        self.buttons = buttons
        self.focus = focus

    def event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_UP, pygame.K_w, pygame.K_LEFT, pygame.K_a):
                self.focus = (self.focus - 1) % len(self.buttons)
                self.app.sound.play("move")
            elif e.key in (pygame.K_DOWN, pygame.K_s, pygame.K_RIGHT, pygame.K_d, pygame.K_TAB):
                self.focus = (self.focus + 1) % len(self.buttons)
                self.app.sound.play("move")
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.activate(self.focus)
                return True
        elif e.type == pygame.MOUSEMOTION:
            vx, vy = self.app.to_virtual(e.pos)
            for i, b in enumerate(self.buttons):
                if b.contains(vx, vy) and self.focus != i:
                    self.focus = i
                    self.app.sound.play("move", 0.5)
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            vx, vy = self.app.to_virtual(e.pos)
            for i, b in enumerate(self.buttons):
                if b.contains(vx, vy):
                    self.activate(i)
                    return True
        return False

    def activate(self, i):
        self.app.sound.play("click")
        self.buttons[i].action()

    def draw(self, ui):
        for i, b in enumerate(self.buttons):
            ui.button(b.rect, b.label, focused=(i == self.focus), primary=b.primary, size=b.size)


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------
class Effects:
    def __init__(self):
        self.particles = []  # [x, y, vx, vy, life, max_life, color, size]
        self.rings = []  # [x, y, life, max_life, color]
        self.shake = 0.0

    def burst(self, x, y, color, n=26, speed=7.0, size=4.5, life=0.7, gravity=True):
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            s = random.uniform(0.3, 1.0) * speed
            lf = random.uniform(0.5, 1.0) * life
            self.particles.append([x, y, math.cos(a) * s, math.sin(a) * s - (2 if gravity else 0),
                                   lf, lf, color, random.uniform(0.5, 1.0) * size])

    def ring(self, x, y, color, life=0.45):
        self.rings.append([x, y, life, life, color])

    def kick(self, amount):
        self.shake = min(14.0, self.shake + amount)

    def update(self, dt):
        frame = dt * 60
        for p in self.particles:
            p[0] += p[2] * frame
            p[1] += p[3] * frame
            p[3] += 0.25 * frame
            p[2] *= 0.985 ** frame
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]
        for r in self.rings:
            r[2] -= dt
        self.rings = [r for r in self.rings if r[2] > 0]
        self.shake = max(0.0, self.shake - 40 * dt)

    def offset(self, scale):
        if self.shake <= 0:
            return 0, 0
        return (random.uniform(-1, 1) * self.shake * scale, random.uniform(-1, 1) * self.shake * scale)

    def draw(self, painter):
        for x, y, life, max_life, color in self.rings:
            t = 1 - life / max_life
            sx, sy = painter.pt(x, y)
            r = painter.ln(20 + 34 * ease_out(t))
            surf = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(surf, (*color, int(200 * (1 - t))), (r + 2, r + 2), r, max(1, painter.ln(3 * (1 - t) + 1)))
            painter.surface.blit(surf, (sx - r - 2, sy - r - 2))
        for x, y, _, _, life, max_life, color, size in self.particles:
            t = life / max_life
            sx, sy = painter.pt(x, y)
            painter.circle(sx, sy, max(1, size * t * painter.scale), color)


# ---------------------------------------------------------------------------
# A running match (also used for the title screen's demo)
# ---------------------------------------------------------------------------
class Sim:
    def __init__(self, map_name, controllers, first_to):
        """controllers: list of "human", "bot" or a trained model, per player."""
        kinds = ["user" if c == "human" else "ai" for c in controllers]
        self.env = TestEnv(kinds[0], kinds[1], None, winning_score=first_to, map_name=map_name)
        self.controllers = [
            None if c == "human" else Bot(self.env, i) if c == "bot" else c
            for i, c in enumerate(controllers)
        ]
        self.obs = self.env.reset()
        self.done = False
        self.interp = Interpolator(self.env)

    @property
    def map(self):
        return self.env.map

    def step(self):
        env = self.env
        n = env.obs_size
        pre = [(p.x, p.y, p.x_v, p.y_v) for p in env.players]
        acts = []
        for i, c in enumerate(self.controllers):
            if c is not None:
                a, _ = c.predict(self.obs[i * n:(i + 1) * n])
                acts.append(a)
        if len(acts) == 2:
            actions = acts
        elif len(acts) == 1:
            actions = acts[0]
        else:
            actions = None

        before = list(env.scores)
        was_sudden = env.timer.sudden_death
        self.interp.before_step()
        self.obs, self.done, _ = env.step(actions)

        events = []
        if env.timer.sudden_death and not was_sudden:
            events.append(("sudden_death",))
        for i in (0, 1):
            if env.scores[i] > before[i]:
                vx, vy = pre[1 - i][0], pre[1 - i][1]
                events.append(("score", i, (min(max(vx, 12), W - 12), min(max(vy, 12), H - 12))))
        if any(e[0] == "score" for e in events) and env.map.reset_round_on_kill:
            self.interp.forget()  # everything was just put back for a new round
        if not events:
            (x1, y1, vx1, vy1), (x2, y2, vx2, vy2) = pre
            p, q = env.players
            d = math.hypot(p.x - q.x, p.y - q.y)
            if d <= p.r + q.r + 1.5:
                dd = math.hypot(x2 - x1, y2 - y1) or 1
                closing = ((vx1 - vx2) * (x2 - x1) + (vy1 - vy2) * (y2 - y1)) / dd
                if closing > 5:
                    events.append(("hit", ((p.x + q.x) / 2, (p.y + q.y) / 2), closing))
        return events

    def draw(self, surface, scale, shake=(0, 0), effects=None, alpha=1.0):
        """alpha: how far into the next physics step we are (0-1), to draw
        positions blended between the last two steps."""
        with self.interp.blended(alpha):
            self._draw(surface, scale, shake, effects)

    def _draw(self, surface, scale, shake, effects):
        painter = Painter(surface, scale, shake)
        painter.background()
        self.map.render(painter)
        timer = self.env.timer
        painter.closing_walls(timer.walls(), W, H, timer.steps / PHYSICS_HZ)
        if effects:
            effects.draw(painter)
        for p in self.env.players:
            painter.player(p)
        for p in self.env.players:
            painter.offscreen_marker(p, W)


def describe(choice):
    if choice == "human":
        return "Human"
    if choice == "bot":
        return "Bot"
    return choice.upper()


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------
class Scene:
    def __init__(self, app):
        self.app = app
        self.t = 0.0

    def event(self, e):
        pass

    def update(self, dt):
        self.t += dt

    def draw(self, ui):
        pass


class TitleScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.demo = Sim("platform", ["bot", "bot"], 10 ** 9)
        for c in self.demo.controllers:
            c.reaction = 0.6
        self.effects = Effects()
        self.acc = 0.0
        self.menu = Menu(app, [
            Button("How to play", (89, 392, 150, 46), lambda: app.go(HowToScene(app))),
            Button("Play", (255, 388, 170, 52), lambda: app.go(MapSelectScene(app)), primary=True, size=21),
            Button("Quit", (441, 392, 150, 46), app.quit),
        ], focus=1)

    def event(self, e):
        self.menu.event(e)

    def update(self, dt):
        super().update(dt)
        self.acc += dt
        while self.acc >= 1 / PHYSICS_HZ:
            self.acc -= 1 / PHYSICS_HZ
            for ev in self.demo.step():
                if ev[0] == "score":
                    victim = self.demo.env.players[1 - ev[1]]
                    self.effects.burst(*ev[2], victim.color, n=18)
                elif ev[0] == "hit":
                    self.effects.burst(*ev[1], theme.TEXT, n=6, speed=4, size=3, life=0.3)
        self.effects.update(dt)

    def draw(self, ui):
        self.demo.draw(ui.surface, ui.s, effects=self.effects, alpha=self.acc * PHYSICS_HZ)
        ui.dim(115)

        # Logo: "bonk" with the o as a ball
        bob = math.sin(self.t * 3) * 4
        cx, cy = W / 2, 84
        size = 104
        left, right = "b", "nk"
        lw, rw = ui.text_width(left, size), ui.text_width(right, size)
        ball_r = 30
        total = lw + ball_r * 2 + 10 + rw
        x0 = cx - total / 2
        ui.text(left, size, theme.TEXT, (x0, cy), anchor="midleft")
        ui.ball(x0 + lw + 5 + ball_r, cy + 14 + bob, ball_r, theme.P1)
        ui.text(right, size, theme.TEXT, (x0 + lw + ball_r * 2 + 10, cy), anchor="midleft")
        ui.ball(x0 + total + 26, cy + 30 - bob, 14, theme.P2)
        ui.text("a tiny physics brawler", 18, theme.TEXT_DIM, (cx, 150), bold=False)

        self.menu.draw(ui)
        ui.text("Enter to play  ·  M to mute", 12, theme.TEXT_FAINT, (cx, 455), bold=False, shadow=False)


class HowToScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.menu = Menu(app, [Button("Back", (280, 420, 120, 38), lambda: app.go(TitleScene(app)))])

    def event(self, e):
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.app.go(TitleScene(self.app))
            return
        self.menu.event(e)

    def draw(self, ui):
        Painter(ui.surface, ui.s).background()
        ui.text("How to play", 30, theme.TEXT, (W / 2, 42))

        ui.panel((30, 72, 300, 140))
        ui.panel((350, 72, 300, 140))
        for i, (x, name, color, move, heavy) in enumerate([
            (30, "Red", theme.P1, ["W", "A", "S", "D"], ["L-Shift"]),
            (350, "Blue", theme.P2, ["up", "left", "down", "right"], ["Space", "R-Shift"]),
        ]):
            ui.ball(x + 30, 100, 11, color)
            ui.text(name, 20, color, (x + 50, 100), anchor="midleft")
            ui.text("Move / jump", 13, theme.TEXT_DIM, (x + 20, 138), anchor="midleft", bold=False, shadow=False)
            kx = x + 130
            for k in move:
                kx += ui.keycap(k, kx, 127) + 5
            ui.text("Go heavy", 13, theme.TEXT_DIM, (x + 20, 178), anchor="midleft", bold=False, shadow=False)
            kx = x + 130
            for k in heavy:
                kx += ui.keycap(k, kx, 167) + 5

        ui.panel((30, 226, 620, 180))
        rules = [
            ("Knock your opponent out.", "Off the screen on open maps, into the red walls on Classic."),
            ("Go heavy to hit harder.", "You get knocked around less but move slower, and it takes a moment to recharge."),
            ("On open maps, up is a jump.", "It only works while you're standing on something. On Classic you can fly."),
            ("Esc pauses the game.", "M toggles sound."),
        ]
        y = 248
        for head, body in rules:
            ui.text("•", 16, theme.ACCENT, (50, y + 8), anchor="midleft")
            ui.text(head, 15, theme.TEXT, (66, y + 8), anchor="midleft")
            ui.text(body, 13, theme.TEXT_DIM, (66, y + 27), anchor="midleft", bold=False, shadow=False)
            y += 39
        self.menu.draw(ui)


class MapSelectScene(Scene):
    CARD_W, CARD_H = 300, 172
    THUMB_H = 104

    def __init__(self, app, selected=None):
        super().__init__(app)
        self.names = [n for n in MAP_ORDER if n in MAPS] + [n for n in MAPS if n not in MAP_ORDER]
        self.focus = self.names.index(selected) if selected in self.names else 0
        self.thumbs = {}

    def card_pos(self, i):
        col, row = i % 2, i // 2
        return 30 + col * (self.CARD_W + 20), 72 + row * (self.CARD_H + 18)

    def thumb(self, name):
        if name not in self.thumbs:
            s = self.app.scale
            surf = pygame.Surface((int(self.CARD_W * s), int(self.THUMB_H * s)))
            m = make_map(name)
            focus_y = getattr(m, "TOP", None) or getattr(m, "FLOOR_Y", None) or 300
            focus_y = focus_y - 40
            k = 0.33 * s
            painter = Painter(surf, k, (surf.get_width() / 2 - W / 2 * k, surf.get_height() / 2 - focus_y * k))
            painter.background()
            m.render(painter)
            p1, p2 = m.make_players()
            lo, hi, _, bottom = m.spawn_box
            for p, fx in ((p1, 0.25), (p2, 0.75)):
                p.x = lo + (hi - lo) * fx
                p.y = bottom - p.r - 1
                painter.player(p)
            self.thumbs[name] = surf
        return self.thumbs[name]

    def choose(self):
        self.app.sound.play("click")
        self.app.go(PlayerSelectScene(self.app, self.names[self.focus]))

    def event(self, e):
        n = len(self.names)
        if e.type == pygame.KEYDOWN:
            moves = {pygame.K_LEFT: -1, pygame.K_a: -1, pygame.K_RIGHT: 1, pygame.K_d: 1,
                     pygame.K_UP: -2, pygame.K_w: -2, pygame.K_DOWN: 2, pygame.K_s: 2, pygame.K_TAB: 1}
            if e.key in moves:
                self.focus = (self.focus + moves[e.key]) % n
                self.app.sound.play("move")
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.choose()
            elif e.key == pygame.K_ESCAPE:
                self.app.go(TitleScene(self.app))
        elif e.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            vx, vy = self.app.to_virtual(e.pos)
            for i in range(n):
                x, y = self.card_pos(i)
                if x <= vx <= x + self.CARD_W and y <= vy <= y + self.CARD_H:
                    if e.type == pygame.MOUSEMOTION and self.focus != i:
                        self.focus = i
                        self.app.sound.play("move", 0.5)
                    elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                        self.focus = i
                        self.choose()

    def draw(self, ui):
        Painter(ui.surface, ui.s).background()
        ui.text("Choose a map", 28, theme.TEXT, (W / 2, 38))
        for i, name in enumerate(self.names):
            cls = MAPS[name]
            x, y = self.card_pos(i)
            focused = i == self.focus
            lift = -3 if focused else 0
            y += lift
            card = ui.panel((x, y, self.CARD_W, self.CARD_H), radius=14,
                            border=theme.ACCENT if focused else theme.PANEL_BORDER,
                            border_w=2.5 if focused else 1.2, alpha=240)
            # Thumbnail with rounded top corners
            thumb = self.thumb(name)
            mask = pygame.Surface(thumb.get_size(), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                             border_top_left_radius=ui.v(13), border_top_right_radius=ui.v(13))
            rounded = thumb.copy().convert_alpha()
            rounded.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            ui.surface.blit(rounded, (card.x, card.y))

            ty = y + self.THUMB_H + 16
            ui.text(cls.title, 17, theme.TEXT, (x + 14, ty), anchor="midleft")
            for j, line in enumerate(ui.wrap(cls.description, 11.5, self.CARD_W - 28)[:2]):
                ui.text(line, 11.5, theme.TEXT_DIM, (x + 14, ty + 19 + j * 15), anchor="midleft",
                        bold=False, shadow=False)
            # Chips on the thumbnail
            chips = ["Fly" if cls.can_fly else "Jump"]
            if self.app.has_agents(name):
                chips.append("AI ready")
            cx = x + self.CARD_W - 10
            for chip in reversed(chips):
                w = ui.text_width(chip, 10.5) + 14
                cx -= w
                ui.panel((cx, y + 8, w, 19), color=theme.PANEL, alpha=200, radius=9, border=None)
                ui.text(chip, 10.5, theme.ACCENT if chip == "AI ready" else theme.TEXT,
                        (cx + w / 2, y + 17.5), shadow=False)
                cx -= 6
        ui.text("Arrows to choose  ·  Enter to select  ·  Esc to go back", 12, theme.TEXT_FAINT,
                (W / 2, 462), bold=False, shadow=False)


class PlayerSelectScene(Scene):
    def __init__(self, app, map_name, picks=None, first_to=None):
        super().__init__(app)
        self.map_name = map_name
        self.map_cls = MAPS[map_name]
        self.agents = app.load_agents(map_name)
        self.options = ["human", "bot"] + list(self.agents)
        default = picks or ("human", "bot")
        self.picks = [self.options.index(p) if p in self.options else 0 for p in default]
        default_first = first_to or min(self.map_cls.winning_score, 10)
        self.first_opts = sorted(set(FIRST_TO_OPTIONS) | {default_first})
        self.first = self.first_opts.index(default_first)
        self.focus = 3  # rows: red, blue, first-to, start
        self.start_btn = Button("Start match", (440, 418, 200, 44), self.start, primary=True, size=18)
        self.back_btn = Button("Back", (40, 418, 120, 44), self.back)

    def choice(self, i):
        o = self.options[self.picks[i]]
        return o if o in ("human", "bot") else self.agents[o]

    def back(self):
        self.app.go(MapSelectScene(self.app, self.map_name))

    def start(self):
        self.app.go(MatchScene(self.app, self.map_name, [self.choice(0), self.choice(1)],
                               [self.options[p] for p in self.picks], self.first_opts[self.first]))

    def change(self, row, d):
        if row in (0, 1):
            self.picks[row] = (self.picks[row] + d) % len(self.options)
        elif row == 2:
            self.first = (self.first + d) % len(self.first_opts)
        else:
            return
        self.app.sound.play("move")

    def arrow_hits(self, vx, vy):
        """(row, delta) for a click on one of the ‹ › arrows, else None."""
        rows = [(0, 40 + 20, 40 + 260, 190), (1, 360 + 20, 360 + 260, 190), (2, 250, 430, 372)]
        for row, left, right, y in rows:
            if abs(vy - y) < 18:
                if abs(vx - left) < 22:
                    return row, -1
                if abs(vx - right) < 22:
                    return row, 1
        return None

    def event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.back()
            elif e.key in (pygame.K_UP, pygame.K_w):
                self.focus = (self.focus - 1) % 4
                self.app.sound.play("move")
            elif e.key in (pygame.K_DOWN, pygame.K_s, pygame.K_TAB):
                self.focus = (self.focus + 1) % 4
                self.app.sound.play("move")
            elif e.key in (pygame.K_LEFT, pygame.K_a):
                self.change(self.focus, -1)
            elif e.key in (pygame.K_RIGHT, pygame.K_d):
                self.change(self.focus, 1)
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.app.sound.play("click")
                self.start()
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            vx, vy = self.app.to_virtual(e.pos)
            hit = self.arrow_hits(vx, vy)
            if hit:
                self.focus = hit[0]
                self.change(*hit)
            elif self.start_btn.contains(vx, vy):
                self.app.sound.play("click")
                self.start()
            elif self.back_btn.contains(vx, vy):
                self.app.sound.play("click")
                self.back()
            else:
                for row, (x, y, w, h) in enumerate([(40, 70, 280, 230), (360, 70, 280, 230)]):
                    if x <= vx <= x + w and y <= vy <= y + h:
                        self.focus = row
        elif e.type == pygame.MOUSEMOTION:
            vx, vy = self.app.to_virtual(e.pos)
            if self.start_btn.contains(vx, vy):
                self.focus = 3

    def draw_selector(self, ui, cx, y, label, focused, width=220):
        if focused:
            ui.panel((cx - width / 2, y - 18, width, 36), color=theme.PANEL_LIGHT, radius=18,
                     border=theme.ACCENT, alpha=255, border_w=2)
        arrow_c = theme.ACCENT if focused else theme.TEXT_FAINT
        ui.chevron(cx - width / 2 + 18, y, -1, 7, arrow_c, width=2.5)
        ui.chevron(cx + width / 2 - 18, y, 1, 7, arrow_c, width=2.5)
        ui.text(label, 19, theme.TEXT, (cx, y))

    def draw(self, ui):
        Painter(ui.surface, ui.s).background()
        ui.text(self.map_cls.title, 26, theme.TEXT, (W / 2, 34))
        ui.text("Who's playing?", 13, theme.TEXT_DIM, (W / 2, 58), bold=False, shadow=False)

        for i, (x, color) in enumerate(((40, theme.P1), (360, theme.P2))):
            focused = self.focus == i
            ui.panel((x, 76, 280, 228), border=color if focused else theme.PANEL_BORDER,
                     border_w=2 if focused else 1.2)
            bob = math.sin(self.t * 3 + i) * 3 if focused else 0
            ui.ball(x + 140, 124 + bob, 26, color)
            ui.text(theme.PLAYER_NAMES[i], 16, color, (x + 140, 164))
            opt = self.options[self.picks[i]]
            self.draw_selector(ui, x + 140, 196, describe(opt), focused)
            if opt == "human":
                keys = ([["W", "A", "S", "D"], ["L-Shift"]] if i == 0
                        else [["up", "left", "down", "right"], ["Space"]])
                for row, (group, label) in enumerate(zip(keys, ("move", "heavy"))):
                    ky = 230 + row * 32
                    kw = sum(ui.keycap_width(k, 11, 20) for k in group) + 4 * (len(group) - 1)
                    lw = ui.text_width(label, 11, bold=False)
                    kx = x + 140 - (kw + 10 + lw) / 2
                    for k in group:
                        kx += ui.keycap(k, kx, ky, h=20, size=11) + 4
                    ui.text(label, 11, theme.TEXT_FAINT, (kx + 6, ky + 10), anchor="midleft",
                            bold=False, shadow=False)
            else:
                desc = "Built-in bot. Not too smart." if opt == "bot" else f"Your trained {opt.upper()} agent."
                ui.text(desc, 12.5, theme.TEXT_DIM, (x + 140, 248), bold=False, shadow=False)

        # First-to row
        focused = self.focus == 2
        ui.text("First to", 13, theme.TEXT_DIM, (W / 2, 344), bold=False, shadow=False)
        self.draw_selector(ui, W / 2, 372, str(self.first_opts[self.first]), focused, width=180)

        if not self.agents:
            ui.text(f"Tip: train AI agents for this map with  python3 main.py --train {self.map_name}",
                    11, theme.TEXT_FAINT, (W / 2, 404), bold=False, shadow=False)

        ui.button(self.back_btn.rect, self.back_btn.label, size=16)
        ui.button(self.start_btn.rect, self.start_btn.label, focused=self.focus == 3, primary=True, size=18)


class MatchScene(Scene):
    COUNTDOWN = 0.55  # seconds per "3, 2, 1"

    def __init__(self, app, map_name, controllers, labels, first_to):
        super().__init__(app)
        self.args = (map_name, controllers, labels, first_to)
        self.map_name = map_name
        self.labels = labels
        self.first_to = first_to
        self.sim = Sim(map_name, controllers, first_to)
        self.effects = Effects()
        self.acc = 0.0
        self.phase = "countdown"
        self.phase_t = 0.0
        self.countdown_len = 3
        self.last_beep = None
        self.banner = None  # (text, color, start_time)
        self.humans = [c == "human" for c in controllers]
        self.paused = False
        self.pause_menu = Menu(app, [
            Button("Resume", (260, 196, 160, 42), self.resume, primary=True),
            Button("Restart", (260, 248, 160, 40), self.restart),
            Button("Main menu", (260, 298, 160, 40), lambda: app.go(TitleScene(app))),
        ])
        for p in self.sim.env.players:
            self.effects.ring(p.x, p.y, p.color)

    def resume(self):
        self.paused = False

    def restart(self):
        self.app.go(MatchScene(self.app, *self.args))

    def set_phase(self, phase, countdown=3):
        self.phase = phase
        self.phase_t = 0.0
        self.countdown_len = countdown
        self.last_beep = None

    def event(self, e):
        if e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_p):
            if self.phase != "over":
                self.paused = not self.paused
                self.app.sound.play("click")
            return
        if self.paused:
            self.pause_menu.event(e)

    def update(self, dt):
        super().update(dt)
        self.effects.update(dt)
        if self.paused:
            return
        self.phase_t += dt

        if self.phase == "countdown":
            n = self.countdown_len
            idx = int(self.phase_t / self.COUNTDOWN)
            if idx != self.last_beep:
                self.last_beep = idx
                self.app.sound.play("beep" if idx < n else "go")
            if self.phase_t >= self.COUNTDOWN * n:
                self.set_phase("play")
                self.banner = ("GO!", theme.ACCENT, self.t)
            return

        if self.phase == "scored":
            if self.phase_t > 1.1:
                for p in self.sim.env.players:
                    self.effects.ring(p.x, p.y, p.color)
                self.set_phase("countdown", countdown=2)
            return

        if self.phase == "over":
            if self.phase_t > 1.4:
                self.app.go(ResultsScene(self.app, self))
            return

        self.acc += dt
        while self.acc >= 1 / PHYSICS_HZ and self.phase == "play":
            self.acc -= 1 / PHYSICS_HZ
            for ev in self.sim.step():
                self.handle(ev)
            if self.sim.done:
                self.set_phase("over")
                self.app.sound.play("win")

    def handle(self, ev):
        env = self.sim.env
        if ev[0] == "score":
            scorer, pos = ev[1], ev[2]
            victim = env.players[1 - scorer]
            self.effects.burst(*pos, victim.color, n=34, speed=9)
            self.effects.burst(*pos, theme.TEXT, n=10, speed=5, size=3)
            self.effects.kick(10)
            self.app.sound.play("death")
            self.app.sound.play("point", 0.7)
            name = theme.PLAYER_NAMES[scorer]
            color = env.players[scorer].color
            if env.map.reset_round_on_kill and not self.sim.done:
                self.banner = (f"{name} scores!", color, self.t)
                self.set_phase("scored")
                self.acc = 0.0
            else:
                self.banner = (f"+1 {name}", color, self.t)
                self.effects.ring(victim.x, victim.y, victim.color)
        elif ev[0] == "sudden_death":
            self.banner = ("Sudden death!", theme.DANGER, self.t)
            self.effects.kick(6)
            self.app.sound.play("go")
        elif ev[0] == "hit":
            pos, strength = ev[1], ev[2]
            self.effects.burst(*pos, theme.TEXT, n=int(4 + strength), speed=strength * 0.5, size=3, life=0.35)
            self.effects.kick(min(8, strength * 0.4))
            self.app.sound.play("hit", min(1.0, strength / 18))

    # --- drawing ------------------------------------------------------------
    def draw_world(self, ui):
        alpha = self.acc * PHYSICS_HZ if self.phase == "play" else 1.0
        self.sim.draw(ui.surface, ui.s, self.effects.offset(ui.s), self.effects, alpha)

    def draw_hud(self, ui):
        env = self.sim.env
        for i in (0, 1):
            color = env.players[i].color
            score = env.scores[i]
            label = describe(self.labels[i])
            pips = self.first_to <= 10
            w = 70 + ui.text_width(label, 13) + (self.first_to * 13 + 8 if pips else 40)
            x = 10 if i == 0 else W - 10 - w
            ui.panel((x, 8, w, 32), alpha=200, radius=16, border=None)
            bx = x + 18 if i == 0 else x + w - 18
            ui.ball(bx, 24, 9, color)
            tx = bx + 16 if i == 0 else bx - 16
            r = ui.text(label, 13, theme.TEXT, (tx, 24), anchor="midleft" if i == 0 else "midright", shadow=False)
            if pips:
                start = r.right / ui.s + 12 if i == 0 else r.left / ui.s - 12 - (self.first_to - 1) * 13
                for k in range(self.first_to):
                    px = start + k * 13
                    filled = (k < score) if i == 0 else (self.first_to - 1 - k < score)
                    sx, sy = ui.v(px), ui.v(24)
                    p = Painter(ui.surface, ui.s)
                    if filled:
                        p.circle(sx, sy, ui.v(5), color)
                    else:
                        pygame.draw.circle(ui.surface, theme.TEXT_FAINT, (sx, sy), ui.v(5), max(1, ui.v(1.3)))
            else:
                sx = r.right / ui.s + 22 if i == 0 else r.left / ui.s - 22
                ui.text(str(score), 18, color, (sx, 24), shadow=False)
        if self.t < 5:
            ui.text(f"{MAPS[self.map_name].title}  ·  first to {self.first_to}", 11, theme.TEXT_DIM,
                    (W / 2, 24), bold=False, shadow=False, alpha=int(255 * min(1.0, 5 - self.t)))

        self.draw_timer(ui)

        # Control hints for human players at the start
        if any(self.humans) and self.t < 6:
            alpha = int(255 * min(1.0, (6 - self.t) / 1.0))
            parts = []
            if self.humans[0]:
                parts.append("Red: WASD + L-Shift")
            if self.humans[1]:
                parts.append("Blue: Arrows + Space")
            hint = "   ·   ".join(parts)
            w = ui.text_width(hint, 12, bold=False) + 28
            ui.panel((W / 2 - w / 2, H - 38, w, 26), alpha=int(190 * alpha / 255), radius=13, border=None)
            ui.text(hint, 12, theme.TEXT_DIM, (W / 2, H - 25), bold=False, shadow=False, alpha=alpha)

    def draw_timer(self, ui):
        timer = self.sim.env.timer
        if not timer.enabled:
            return
        # Shares the bottom of the screen with the control hints, so it
        # fades in as they fade out
        alpha = 255 if not any(self.humans) else int(255 * max(0.0, min(1.0, self.t - 5.5)))
        if alpha <= 0:
            return
        if timer.sudden_death:
            text, color = "SUDDEN DEATH", theme.DANGER
        else:
            left = math.ceil(timer.remaining)
            text = f"{left // 60}:{left % 60:02d}"
            color = theme.ACCENT if left <= 10 else theme.TEXT_DIM
        w = ui.text_width(text, 13) + 28
        ui.panel((W / 2 - w / 2, H - 36, w, 24), alpha=int(190 * alpha / 255), radius=12, border=None)
        ui.text(text, 13, color, (W / 2, H - 24), shadow=False, alpha=alpha)

    def draw_center(self, ui):
        if self.phase == "countdown":
            n = self.countdown_len
            idx = int(self.phase_t / self.COUNTDOWN)
            if idx < n:
                t = (self.phase_t % self.COUNTDOWN) / self.COUNTDOWN
                label = str(n - idx) if n == 3 else ("Ready" if idx == 0 else "Set")
                ui.text(label, 64, theme.TEXT, (W / 2, 150), scale=0.6 + 0.4 * ease_out_back(t * 2),
                        alpha=int(255 * min(1, (1 - t) * 3)))
        if self.banner:
            text, color, start = self.banner
            age = self.t - start
            if age < 1.1:
                size = 46 if text == "GO!" else 34
                alpha = int(255 * min(1.0, (1.1 - age) * 4))
                ui.text(text, size, color, (W / 2, 150 if text == "GO!" else 90),
                        scale=0.5 + 0.5 * ease_out_back(age * 4), alpha=alpha)
                if text != "GO!" and self.phase == "scored":
                    s = self.sim.env.scores
                    ui.text(f"{s[0]}  –  {s[1]}", 20, theme.TEXT, (W / 2, 126), alpha=alpha)

    def draw(self, ui):
        self.draw_world(ui)
        self.draw_hud(ui)
        self.draw_center(ui)
        if self.paused:
            ui.dim(160)
            ui.panel((220, 120, 240, 236), alpha=250)
            ui.text("Paused", 26, theme.TEXT, (W / 2, 158))
            self.pause_menu.draw(ui)


class ResultsScene(Scene):
    def __init__(self, app, match):
        super().__init__(app)
        self.match = match
        env = match.sim.env
        s = env.scores
        self.winner = 0 if s[0] > s[1] else 1 if s[1] > s[0] else None
        self.effects = Effects()
        if self.winner is not None:
            color = env.players[self.winner].color
            for _ in range(3):
                self.effects.burst(random.uniform(150, 530), random.uniform(120, 200), color, n=25, speed=8, life=1.6)
                self.effects.burst(random.uniform(150, 530), random.uniform(120, 200), theme.ACCENT, n=12, speed=7, life=1.6)
        map_name, controllers, labels, first_to = match.args
        self.menu = Menu(app, [
            Button("Rematch", (240, 270, 200, 44), match.restart, primary=True, size=18),
            Button("Change players", (240, 324, 200, 38),
                   lambda: app.go(PlayerSelectScene(app, map_name, labels, first_to))),
            Button("Main menu", (240, 370, 200, 38), lambda: app.go(TitleScene(app))),
        ])

    def event(self, e):
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.app.go(TitleScene(self.app))
            return
        self.menu.event(e)

    def update(self, dt):
        super().update(dt)
        self.effects.update(dt)

    def draw(self, ui):
        self.match.sim.draw(ui.surface, ui.s)
        ui.dim(170)
        self.effects.draw(Painter(ui.surface, ui.s))
        ui.panel((200, 92, 280, 336), alpha=250)
        s = self.match.sim.env.scores
        if self.winner is None:
            ui.text("Draw!", 36, theme.TEXT, (W / 2, 150))
        else:
            color = self.match.sim.env.players[self.winner].color
            bob = math.sin(self.t * 4) * 4
            ui.ball(W / 2, 140 + bob, 24, color)
            ui.text(f"{theme.PLAYER_NAMES[self.winner]} wins!", 32, color, (W / 2, 196),
                    scale=0.7 + 0.3 * ease_out_back(self.t * 3))
        ui.text(f"{s[0]}  –  {s[1]}", 22, theme.TEXT, (W / 2, 236))
        self.menu.draw(ui)


# ---------------------------------------------------------------------------
class App:
    def __init__(self):
        pygame.init()
        info = pygame.display.Info()
        sw, sh = info.current_w or 1280, info.current_h or 800
        self.scale = max(1.0, min(1.75, (sw * 0.9) / W, (sh * 0.85) / H))
        pygame.display.set_caption("bonk")
        self._set_icon()
        self.screen = pygame.display.set_mode((int(W * self.scale), int(H * self.scale)))
        self.ui = UI(self.screen, self.scale)
        self.clock = pygame.time.Clock()
        self.sound = Sound()
        self.running = True
        self.toast = None
        self._agents = {}
        self.scene = TitleScene(self)

    def _set_icon(self):
        icon = pygame.Surface((64, 64), pygame.SRCALPHA)
        pygame.draw.circle(icon, theme.darken(theme.P1, 0.5), (32, 32), 28)
        pygame.draw.circle(icon, theme.P1, (32, 32), 24)
        pygame.draw.circle(icon, theme.lighten(theme.P1, 0.55), (24, 23), 6)
        pygame.display.set_icon(icon)

    def to_virtual(self, pos):
        return pos[0] / self.scale, pos[1] / self.scale

    def go(self, scene):
        self.scene = scene

    def quit(self):
        self.running = False

    def has_agents(self, map_name):
        from bonk_game.envs.utils.maps import agent_dir
        d = agent_dir(map_name)
        return any(os.path.exists(f"{d}/{k}.zip") for k in ("ppo", "a2c", "dqn", "ars", "bad"))

    def load_agents(self, map_name):
        """Trained agents for a map (empty if none, or no stable-baselines3)."""
        if map_name not in self._agents:
            agents = {}
            if self.has_agents(map_name):
                self.show_message("Loading agents…")
                try:
                    from bonk_game.envs.utils.testing import load_agents, model_classes
                    agents = load_agents(model_classes(), map_name)
                except Exception:
                    agents = {}
            self._agents[map_name] = agents
        return self._agents[map_name]

    def show_message(self, text):
        Painter(self.screen, self.scale).background()
        self.ui.text(text, 20, theme.TEXT_DIM, (W / 2, H / 2))
        pygame.display.flip()

    def run(self):
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, 1 / 15)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.running = False
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_m:
                    muted = self.sound.toggle_mute()
                    self.toast = ("Sound off" if muted else "Sound on", 1.2)
                else:
                    self.scene.event(e)
            self.scene.update(dt)
            self.scene.draw(self.ui)
            if self.toast:
                text, left = self.toast
                w = self.ui.text_width(text, 12) + 26
                self.ui.panel((W - w - 12, H - 36, w, 26), alpha=210, radius=13, border=None)
                self.ui.text(text, 12, theme.TEXT, (W - 12 - w / 2, H - 23), shadow=False)
                left -= dt
                self.toast = (text, left) if left > 0 else None
            pygame.display.flip()
        pygame.quit()


def run():
    App().run()
