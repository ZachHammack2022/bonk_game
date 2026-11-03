"""Colours and fonts shared by the whole game."""
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

# Backdrop
BG_TOP = (24, 33, 52)
BG_BOTTOM = (46, 64, 96)

# Text and panels
TEXT = (241, 245, 249)
TEXT_DIM = (160, 174, 198)
TEXT_FAINT = (110, 124, 150)
ACCENT = (255, 209, 102)
PANEL = (19, 27, 43)
PANEL_LIGHT = (32, 44, 68)
PANEL_BORDER = (64, 84, 120)

# Players
P1 = (255, 107, 107)
P2 = (77, 171, 247)
P3 = (177, 132, 255)
P4 = (255, 202, 58)
PLAYER_COLORS = (P1, P2, P3, P4)
PLAYER_NAMES = ("Red", "Blue", "Purple", "Yellow")

# Level pieces
PLATFORM = (126, 214, 170)
POST = (104, 120, 156)
HAZARD = (239, 83, 80)
PAD = (178, 236, 94)
PIT = (96, 168, 132)
WOOD = (214, 160, 96)
ROPE = (176, 142, 104)
RAIL = (120, 136, 170)
DANGER = (239, 83, 80)

_FONT_NAMES = "nunito,avenirnextrounded,avenirnext,avenir,helveticaneue,inter,segoeui,dejavusans,arial"
_fonts = {}


def font(size, bold=True):
    """A cached UI font. `size` is in screen pixels."""
    key = (int(size), bold)
    if not pygame.font.get_init():
        # Fonts from before a pygame.quit() are dead; start a fresh cache
        _fonts.clear()
        pygame.font.init()
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont(_FONT_NAMES, max(8, int(size)), bold=bold)
    return _fonts[key]


def lighten(color, amount):
    return tuple(min(255, int(c + (255 - c) * amount)) for c in color[:3])


def darken(color, amount):
    return tuple(max(0, int(c * (1 - amount))) for c in color[:3])


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
