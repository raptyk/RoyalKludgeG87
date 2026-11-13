"""Keyboard preview model: physical layout and a rough simulation of the effects.

The firmware effects run on the keyboard and are not documented, so the
animations here are only approximations meant to give an impression of the
effect; they are not a faithful reproduction.
"""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass

from .keys import key_index
from .lighting import CUSTOM_MODE, Color, LightingState, ModeSettings

CELL = 4  # terminal columns per key unit (one normal key)
NAV_GAP = 2

# One entry per row: (key name, width in columns); a name of None is a gap.
# Every main row is 60 columns wide (15 key units).
_FUNCTION_ROW = [
    ("esc", 4), (None, 2),
    ("f1", 4), ("f2", 4), ("f3", 4), ("f4", 4), (None, 2),
    ("f5", 4), ("f6", 4), ("f7", 4), ("f8", 4), (None, 2),
    ("f9", 4), ("f10", 4), ("f11", 4), ("f12", 4), (None, 2),
]


def _keys(names: str | tuple[str, ...], width: int = CELL) -> list[tuple[str | None, int]]:
    return [(name, width) for name in names]


_MAIN_ROWS: list[list[tuple[str | None, int]]] = [
    _FUNCTION_ROW,
    [*_keys("`1234567890-="), ("backspace", 8)],
    [("tab", 6), *_keys("qwertyuiop[]"), ("\\", 6)],
    [("capslock", 7), *_keys("asdfghjkl;'"), ("enter", 9)],
    [("lshift", 9), *_keys("zxcvbnm,./"), ("rshift", 11)],
    [("lctrl", 5), ("lwin", 5), ("lalt", 5), ("space", 25), ("ralt", 5), ("fn", 5), ("app", 5), ("rctrl", 5)],
]
_NAV_ROWS: list[list[tuple[str | None, int]]] = [
    _keys(("printscreen", "scrolllock", "pause")),
    _keys(("insert", "home", "pageup")),
    _keys(("delete", "end", "pagedown")),
    [],
    [(None, CELL), ("up", CELL)],
    _keys(("left", "down", "right")),
]

LABELS = {
    "esc": "Esc", "backspace": "Bksp", "tab": "Tab", "capslock": "Caps", "enter": "Enter",
    "lshift": "Shift", "rshift": "Shift", "lctrl": "Ctrl", "rctrl": "Ctrl", "lwin": "Win",
    "lalt": "Alt", "ralt": "Alt", "fn": "Fn", "app": "Menu", "space": "",
    "printscreen": "Prt", "scrolllock": "Scr", "pause": "Pau", "insert": "Ins", "home": "Hom",
    "pageup": "PgU", "delete": "Del", "end": "End", "pagedown": "PgD",
    "up": "↑", "down": "↓", "left": "←", "right": "→",
}


@dataclass(frozen=True)
class KeyCell:
    name: str
    row: int
    col: int  # first terminal column
    width: int  # columns including the one-column gap after the key
    label: str
    index: int  # position in the 8 x 18 lighting matrix

    @property
    def x(self) -> float:
        """Horizontal centre in key units."""
        return (self.col + self.width / 2) / CELL

    @property
    def y(self) -> float:
        return float(self.row)


def _build_layout() -> tuple[KeyCell, ...]:
    cells = []
    for row, (main, nav) in enumerate(zip(_MAIN_ROWS, _NAV_ROWS)):
        col = 0
        for name, width in [*main, *([(None, NAV_GAP), *nav] if nav else [])]:
            if name is not None:
                label = LABELS.get(name, name.upper())
                cells.append(KeyCell(name, row, col, width, label, key_index(name)))
            col += width
    return tuple(cells)


KEYS = _build_layout()
ROWS = len(_MAIN_ROWS)
LAYOUT_WIDTH = max(key.col + key.width for key in KEYS)
ROW_KEYS = tuple(tuple(key for key in KEYS if key.row == row) for row in range(ROWS))

WIDTH = LAYOUT_WIDTH / CELL  # in key units
CENTER_X = WIDTH / 2
CENTER_Y = (ROWS - 1) / 2


def key_at(row: int, col: int) -> str | None:
    """Name of the key drawn at a terminal position, if any."""
    if not 0 <= row < ROWS:
        return None
    for key in ROW_KEYS[row]:
        if key.col <= col < key.col + key.width - 1:
            return key.name
    return None


# -- effect model -----------------------------------------------------------

OFF: Color = (0, 0, 0)
RAINBOW_EFFECTS = frozenset({"colourful", "spectrum"})


def _noise(a: int, b: int) -> float:
    """Deterministic pseudo random number in 0..1."""
    h = (a * 374761393 + b * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return (h & 0xFFFF) / 0xFFFF


def _triangle(value: float) -> float:
    value %= 2
    return value if value <= 1 else 2 - value


def _sweep(u: float, head: float, period: float, width: float) -> float:
    """A bright head moving towards higher u, leaving a fading tail."""
    return max(0.0, 1 - ((head - u) % period) / width)


def _axis(key: KeyCell, direction: int) -> float:
    """Coordinate along the effect's direction (0 right, 1 left, 2 down, 3 up)."""
    if direction == 1:
        return WIDTH - key.x
    if direction == 2:
        return key.y * 3.5
    if direction == 3:
        return (ROWS - 1 - key.y) * 3.5
    return key.x


def _tap(key: KeyCell, p: float) -> float:
    """Simulated key press: 1 right after the press, fading to 0."""
    phase = (p * 0.8 + _noise(key.index, 1) * 6) % 6
    return max(0.0, 1 - phase)


def _static(key, p, direction):
    return 1.0, key.x / WIDTH


def _single_on(key, p, direction):
    return _tap(key, p), None


def _single_off(key, p, direction):
    return 1 - _tap(key, p), None


def _glittering(key, p, direction):
    return 0.12 + (0.88 if _noise(key.index, int(p * 3)) > 0.85 else 0.0), None


def _falling(key, p, direction):
    head = (p * 3 + _noise(int(key.x), 7) * ROWS * 2) % (ROWS * 2)
    behind = head - key.y
    return (max(0.0, 1 - behind / 3) if 0 <= behind < 3 else 0.0), None


def _colourful(key, p, direction):
    return 1.0, key.x / WIDTH + p * 0.1


def _breath(key, p, direction):
    return 0.5 + 0.5 * math.sin(2 * math.pi * p * 0.25), None


def _spectrum(key, p, direction):
    return 1.0, p * 0.08


def _outward(key, p, direction):
    distance = math.hypot(key.x - CENTER_X, key.y - CENTER_Y)
    return max(0.0, math.cos(2 * math.pi * (distance / 8 - p * 0.2))) ** 2, None


def _scrolling(key, p, direction):
    return _sweep(_axis(key, direction), p * 4, WIDTH + 6, 5), None


def _rolling(key, p, direction):
    u = _axis(key, direction) + (key.y * 2 if direction < 2 else key.x * 0.5)
    return _sweep(u, p * 4, WIDTH + 12, 6), None


def _rotating(key, p, direction):
    angle = math.atan2(key.y - CENTER_Y, key.x - CENTER_X) / (2 * math.pi)
    return max(0.0, 1 - ((p * 0.15 - angle) % 1) * 3), None


def _explode(key, p, direction):
    radius = (p * 2) % 12
    distance = math.hypot(key.x - CENTER_X, key.y - CENTER_Y)
    return max(0.0, 1 - abs(distance - radius) / 1.5), None


def _launch(key, p, direction):
    v = (key.y + p * 3 + _noise(int(key.x), 3) * 8) % 8
    return max(0.0, 1 - v / 2), None


def _ripples(key, p, direction):
    level = 0.0
    for source in range(3):
        cycle = p / 3 + source / 3
        epoch = int(cycle)
        age = (cycle - epoch) * 3
        cx = _noise(source, epoch) * WIDTH
        cy = _noise(source + 5, epoch) * (ROWS - 1)
        distance = math.hypot(key.x - cx, key.y - cy)
        level = max(level, max(0.0, 1 - abs(distance - age * 5) / 1.3) * (1 - age / 3))
    return level, None


def _flowing(key, p, direction):
    u = _axis(key, direction)
    return 0.5 + 0.5 * math.sin(u * 0.6 - p * math.pi + key.y * 0.5), None


def _pulsating(key, p, direction):
    return abs(math.sin(math.pi * (p * 0.3 + key.y * 0.04))), None


def _tilt(key, p, direction):
    u = _axis(key, direction) * 0.5 + key.y * 0.8
    return ((u * 0.25 - p * 0.15) % 1) ** 0.5, None


def _shuttle(key, p, direction):
    if direction >= 2:
        position = _triangle(p * 0.12) * (ROWS - 1)
        return max(0.0, 1 - abs(key.y - position) / 1.2), None
    position = _triangle(p * 0.12) * WIDTH
    return max(0.0, 1 - abs(key.x - position) / 2.5), None


EFFECTS = {
    "static": _static, "single-on": _single_on, "single-off": _single_off,
    "glittering": _glittering, "falling": _falling, "colourful": _colourful,
    "breath": _breath, "spectrum": _spectrum, "outward": _outward,
    "scrolling": _scrolling, "rolling": _rolling, "rotating": _rotating,
    "explode": _explode, "launch": _launch, "ripples": _ripples,
    "flowing": _flowing, "pulsating": _pulsating, "tilt": _tilt, "shuttle": _shuttle,
}


def _scale(color: Color, factor: float) -> Color:
    factor = min(1.0, max(0.0, factor))
    return tuple(round(c * factor) for c in color)  # type: ignore[return-value]


def effect_color(mode: str, settings: ModeSettings, key: KeyCell, t: float) -> Color:
    """Colour of one key at time t (seconds) for a built-in effect."""
    p = t * (0.3 + 0.15 * settings.speed)
    level, hue = EFFECTS[mode](key, p, settings.direction)
    if settings.full_color or mode in RAINBOW_EFFECTS:
        if hue is None:
            hue = key.x / WIDTH + p * 0.15
        base = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue % 1.0, 1.0, 1.0))
    else:
        base = settings.color
    return _scale(base, level * settings.brightness / 16)  # type: ignore[arg-type]


def frame(state: LightingState, t: float) -> dict[str, Color]:
    """Colour of every key of the active mode at time t."""
    if state.active == CUSTOM_MODE:
        factor = state.custom_brightness / 16
        return {key.name: _scale(state.custom_colors[key.index], factor) for key in KEYS}
    settings = state.modes[state.active]
    return {key.name: effect_color(state.active, settings, key, t) for key in KEYS}
