"""Key names and their position in the 8 x 18 lighting matrix."""

from __future__ import annotations

MATRIX_ROWS = 8
MATRIX_COLUMNS = 18
MATRIX_SIZE = MATRIX_ROWS * MATRIX_COLUMNS

# name -> (row, column), taken from the vendor tool's KeyboardIDMapping.xml.
# The table also lists numpad keys that the 87 key board does not have.
KEY_POSITIONS: dict[str, tuple[int, int]] = {
    "esc": (0, 1), "f1": (0, 2), "f2": (0, 3), "f3": (0, 4), "f4": (0, 5), "f5": (0, 6),
    "f6": (0, 7), "f7": (0, 8), "f8": (0, 9), "f9": (0, 10), "f10": (0, 11), "f11": (0, 12),
    "f12": (0, 13),
    "`": (1, 1), "1": (1, 2), "2": (1, 3), "3": (1, 4), "4": (1, 5), "5": (1, 6), "6": (1, 7),
    "7": (1, 8), "8": (1, 9), "9": (1, 10), "0": (1, 11), "-": (1, 12), "=": (1, 13),
    "numlock": (1, 14), "num/": (1, 15), "num*": (1, 16),
    "tab": (2, 1), "q": (2, 2), "w": (2, 3), "e": (2, 4), "r": (2, 5), "t": (2, 6), "y": (2, 7),
    "u": (2, 8), "i": (2, 9), "o": (2, 10), "p": (2, 11), "[": (2, 12), "]": (2, 13),
    "num7": (2, 14), "num8": (2, 15), "num9": (2, 16),
    "capslock": (3, 1), "a": (3, 2), "s": (3, 3), "d": (3, 4), "f": (3, 5), "g": (3, 6),
    "h": (3, 7), "j": (3, 8), "k": (3, 9), "l": (3, 10), ";": (3, 11), "'": (3, 12),
    "\\": (3, 13), "num4": (3, 14), "num5": (3, 15), "num6": (3, 16),
    "lshift": (4, 1), "z": (4, 2), "x": (4, 3), "c": (4, 4), "v": (4, 5), "b": (4, 6),
    "n": (4, 7), "m": (4, 8), ",": (4, 9), ".": (4, 10), "/": (4, 11), "rshift": (4, 12),
    "enter": (4, 13), "num1": (4, 14), "num2": (4, 15), "num3": (4, 16),
    "lctrl": (5, 1), "lwin": (5, 2), "lalt": (5, 3), "space": (5, 4), "ralt": (5, 5),
    "fn": (5, 6), "app": (5, 7), "rctrl": (5, 8), "left": (5, 9), "down": (5, 10),
    "up": (5, 11), "right": (5, 12), "backspace": (5, 13), "num0": (5, 14), "num.": (5, 15),
    "numenter": (5, 16),
    "printscreen": (6, 4), "scrolllock": (6, 5), "pause": (6, 7), "insert": (6, 8),
    "home": (6, 9), "pageup": (6, 10), "delete": (6, 11), "end": (6, 12), "pagedown": (6, 13),
    "num-": (6, 14), "num+": (6, 15),
}


def matrix_index(row: int, column: int) -> int:
    if not (0 <= row < MATRIX_ROWS and 0 <= column < MATRIX_COLUMNS):
        raise ValueError(f"matrix position {row}_{column} out of range")
    return row * MATRIX_COLUMNS + column


def key_index(name: str) -> int:
    """Resolve a key name or a raw "row_column" position to a matrix index."""
    normalized = name.strip().lower().replace(" ", "")
    if normalized in KEY_POSITIONS:
        return matrix_index(*KEY_POSITIONS[normalized])
    row, separator, column = normalized.partition("_")
    if separator and row.isdigit() and column.isdigit():
        return matrix_index(int(row), int(column))
    raise KeyError(f"unknown key name: {name!r}")
