"""Little synthesized sound effects, so the game ships with no audio files.

If there's no audio device (or numpy/mixer trouble) everything silently
becomes a no-op.
"""
import os

import numpy as np

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

RATE = 44100


def _env(n, attack=0.005, decay=6.0):
    t = np.arange(n) / RATE
    a = np.minimum(1.0, t / max(attack, 1e-4))
    return a * np.exp(-decay * t)


def _tone(freq, dur, decay=6.0, shape="sine", sweep_to=None):
    n = int(RATE * dur)
    f = np.full(n, float(freq)) if sweep_to is None else np.linspace(freq, sweep_to, n)
    phase = 2 * np.pi * np.cumsum(f) / RATE
    if shape == "square":
        wave = np.sign(np.sin(phase)) * 0.5
    elif shape == "tri":
        wave = 2 / np.pi * np.arcsin(np.sin(phase))
    else:
        wave = np.sin(phase)
    return wave * _env(n, decay=decay)


def _noise(dur, decay=30.0):
    n = int(RATE * dur)
    rng = np.random.default_rng(1)
    return rng.uniform(-1, 1, n) * _env(n, attack=0.001, decay=decay)


def _seq(*parts, gap=0.0):
    out = []
    for p in parts:
        out.append(p)
        if gap:
            out.append(np.zeros(int(RATE * gap)))
    return np.concatenate(out)


def _add(*waves):
    """Mix clips of different lengths."""
    out = np.zeros(max(len(w) for w in waves))
    for w in waves:
        out[:len(w)] += w
    return out


def _build():
    return {
        "click": _tone(1300, 0.04, decay=60, shape="tri") * 0.35,
        "move": _tone(900, 0.03, decay=80, shape="tri") * 0.2,
        "hit": _add(_tone(150, 0.12, decay=28) * 0.9, _noise(0.05, decay=70) * 0.35),
        "bump": _tone(220, 0.06, decay=50) * 0.5,
        "death": _tone(620, 0.38, decay=5, shape="tri", sweep_to=110) * 0.55,
        "beep": _tone(660, 0.1, decay=25, shape="tri") * 0.45,
        "go": _tone(990, 0.22, decay=10, shape="tri") * 0.5,
        "point": _seq(_tone(784, 0.08, decay=25, shape="tri"), _tone(1046, 0.16, decay=14, shape="tri")) * 0.45,
        "win": _seq(*(_tone(f, 0.13, decay=12, shape="tri") for f in (523, 659, 784)),
                    _tone(1046, 0.45, decay=5, shape="tri")) * 0.45,
    }


class Sound:
    def __init__(self):
        self.enabled = False
        self.muted = False
        self.sounds = {}
        try:
            pygame.mixer.pre_init(RATE, -16, 2, 512)
            pygame.mixer.init()
            _, _, channels = pygame.mixer.get_init()
            for name, wave in _build().items():
                data = (np.clip(wave, -1, 1) * 32767).astype(np.int16)
                if channels > 1:
                    data = np.repeat(data[:, None], channels, axis=1)
                self.sounds[name] = pygame.sndarray.make_sound(np.ascontiguousarray(data))
            self.enabled = True
        except Exception:
            self.enabled = False

    def play(self, name, volume=1.0):
        if not self.enabled or self.muted or name not in self.sounds:
            return
        snd = self.sounds[name]
        snd.set_volume(max(0.0, min(1.0, volume)))
        snd.play()

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted
