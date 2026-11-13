"""Lighting state model and its binary encoding."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import protocol
from .keys import MATRIX_COLUMNS, MATRIX_ROWS, MATRIX_SIZE

Color = tuple[int, int, int]

# Built-in effects in firmware order. Effect n is stored in slot n - 1.
MODE_NAMES: tuple[str, ...] = (
    "static", "single-on", "single-off", "glittering", "falling", "colourful", "breath",
    "spectrum", "outward", "scrolling", "rolling", "rotating", "explode", "launch",
    "ripples", "flowing", "pulsating", "tilt", "shuttle",
)
MODE_COUNT = len(MODE_NAMES)
CUSTOM_MODE = "custom"
CUSTOM_SLOT = MODE_COUNT  # slot 19
CUSTOM_MODE_ID = 0x80

SLOT_COUNT = 32
RECORD_SIZE = 16
RECORDS_SIZE = SLOT_COUNT * RECORD_SIZE  # 0x200
KEY_COLORS_OFFSET = RECORDS_SIZE
KEY_COLOR_SIZE = 4
KEY_COLORS_SIZE = MATRIX_SIZE * KEY_COLOR_SIZE  # 0x240
ACTIVE_RECORD_OFFSET = KEY_COLORS_OFFSET + KEY_COLORS_SIZE  # 0x440
LIGHTING_BLOCK_SIZE = 0x480  # the active record is followed by 0x30 bytes of padding

LEVEL_MIN = 1
LEVEL_MAX = 16
DIRECTION_MAX = 3

DEFAULT_COLOR: Color = (0, 0, 255)

# The vendor tool replaces these exact colours before sending them, presumably
# to compensate for the LEDs: (r, g, b) picked in the UI -> value sent.
VENDOR_COLOR_CORRECTION: dict[Color, Color] = {
    (0x00, 0x96, 0xFF): (0x40, 0xB0, 0xFF),
    (0x00, 0x00, 0xFF): (0x30, 0x80, 0xFF),
    (0x00, 0x00, 0x96): (0x30, 0x30, 0xFF),
}

# First KeyLightMode value of the generic effects in the vendor database.
GKDB_FIRST_GENERIC_MODE = 9
GKDB_CUSTOM_MODE = GKDB_FIRST_GENERIC_MODE + SLOT_COUNT - 1  # 40


def parse_color(text: str) -> Color:
    value = text.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"colour must look like RRGGBB, got {text!r}")
    number = int(value, 16)
    return (number >> 16) & 0xFF, (number >> 8) & 0xFF, number & 0xFF


def format_color(color: Color) -> str:
    return "#%02x%02x%02x" % tuple(color)


def _check_level(name: str, value: int) -> int:
    if not LEVEL_MIN <= value <= LEVEL_MAX:
        raise ValueError(f"{name} must be between {LEVEL_MIN} and {LEVEL_MAX}")
    return value


@dataclass
class ModeSettings:
    color: Color = DEFAULT_COLOR
    full_color: bool = False
    brightness: int = 16
    speed: int = 12
    direction: int = 0

    def validate(self) -> None:
        _check_level("brightness", self.brightness)
        _check_level("speed", self.speed)
        if not 0 <= self.direction <= DIRECTION_MAX:
            raise ValueError(f"direction must be between 0 and {DIRECTION_MAX}")
        if len(self.color) != 3 or not all(0 <= c <= 255 for c in self.color):
            raise ValueError("colour components must be between 0 and 255")


@dataclass
class LightingState:
    """Everything the keyboard stores about lighting.

    The firmware offers no way to read the block back, so the tool keeps this
    state on disk and always sends it as a whole.
    """

    active: str = MODE_NAMES[0]
    modes: dict[str, ModeSettings] = field(default_factory=lambda: {name: ModeSettings() for name in MODE_NAMES})
    custom_brightness: int = 16
    custom_colors: list[Color] = field(default_factory=lambda: [(0, 0, 0)] * MATRIX_SIZE)

    def validate(self) -> None:
        if self.active != CUSTOM_MODE and self.active not in MODE_NAMES:
            raise ValueError(f"unknown active mode {self.active!r}")
        for name in MODE_NAMES:
            self.modes[name].validate()
        _check_level("custom brightness", self.custom_brightness)
        if len(self.custom_colors) != MATRIX_SIZE:
            raise ValueError(f"custom colours must have {MATRIX_SIZE} entries")

    # -- persistence --------------------------------------------------------

    def to_json(self) -> str:
        document = {
            "active": self.active,
            "modes": {
                name: {**asdict(settings), "color": format_color(settings.color)}
                for name, settings in self.modes.items()
            },
            "custom": {
                "brightness": self.custom_brightness,
                "colors": [format_color(color) for color in self.custom_colors],
            },
        }
        return json.dumps(document, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "LightingState":
        document = json.loads(text)
        state = cls()
        state.active = document.get("active", state.active)
        for name, raw in document.get("modes", {}).items():
            if name not in MODE_NAMES:
                continue
            state.modes[name] = ModeSettings(
                color=parse_color(raw["color"]),
                full_color=bool(raw["full_color"]),
                brightness=int(raw["brightness"]),
                speed=int(raw["speed"]),
                direction=int(raw["direction"]),
            )
        custom = document.get("custom", {})
        state.custom_brightness = int(custom.get("brightness", state.custom_brightness))
        if "colors" in custom:
            state.custom_colors = [parse_color(value) for value in custom["colors"]]
        state.validate()
        return state

    @classmethod
    def load(cls, path: Path) -> "LightingState":
        if not path.exists():
            return cls()
        return cls.from_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json() + "\n", encoding="utf-8")


def default_state_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "g87ctl" / "state.json"


# -- encoding ---------------------------------------------------------------


def mode_id(name: str) -> int:
    return MODE_NAMES.index(name) + 1


def resolve_mode(text: str) -> str:
    """Accept a mode name or its 1 based number."""
    value = text.strip().lower()
    if value in MODE_NAMES or value == CUSTOM_MODE:
        return value
    if value.isdigit() and 1 <= int(value) <= MODE_COUNT:
        return MODE_NAMES[int(value) - 1]
    if value.isdigit() and int(value) > MODE_COUNT:
        raise ValueError(
            f"effect {value} is hidden; use: g87ctl experimental effect {value} [options] --yes"
        )
    raise ValueError(f"unknown lighting mode {text!r} (try 'g87ctl modes')")


def encode_mode_record(effect_id: int, settings: ModeSettings) -> bytes:
    record = bytearray(RECORD_SIZE)
    record[0] = effect_id
    record[1:4] = bytes(settings.color)
    record[8] = 1 if settings.full_color else 0
    record[9] = settings.brightness
    record[10] = settings.speed
    record[11] = settings.direction
    record[14:16] = protocol.BLOCK_TERMINATOR
    return bytes(record)


def encode_custom_record(brightness: int) -> bytes:
    record = bytearray(RECORD_SIZE)
    record[0] = CUSTOM_MODE_ID
    record[9] = brightness
    record[14:16] = protocol.BLOCK_TERMINATOR
    return bytes(record)


def build_lighting_block(state: LightingState) -> bytes:
    """Encode the 0x480 byte payload of the lighting write command."""
    state.validate()
    block = bytearray(LIGHTING_BLOCK_SIZE)
    records = [encode_mode_record(mode_id(name), state.modes[name]) for name in MODE_NAMES]
    records.append(encode_custom_record(state.custom_brightness))
    for slot, record in enumerate(records):
        block[slot * RECORD_SIZE : (slot + 1) * RECORD_SIZE] = record
    for index, color in enumerate(state.custom_colors):
        offset = KEY_COLORS_OFFSET + index * KEY_COLOR_SIZE
        block[offset] = CUSTOM_MODE_ID
        block[offset + 1 : offset + 4] = bytes(color)
    active_slot = CUSTOM_SLOT if state.active == CUSTOM_MODE else MODE_NAMES.index(state.active)
    block[ACTIVE_RECORD_OFFSET : ACTIVE_RECORD_OFFSET + RECORD_SIZE] = records[active_slot]
    return bytes(block)


def build_profile_block(
    state: LightingState,
    gaming_mode: bool = False,
    disabled_keys: tuple[bool, bool, bool] = (False, False, False),
) -> bytes:
    """Encode the 64 byte profile summary block.

    Byte 0 is the vendor's light mode number clamped to 10: values up to 8 are
    effects of an older keyboard family, 9 is the first generic effect.
    """
    block = bytearray(protocol.PACKET_SIZE)
    if state.active == CUSTOM_MODE:
        vendor_mode = GKDB_CUSTOM_MODE
    else:
        vendor_mode = GKDB_FIRST_GENERIC_MODE + MODE_NAMES.index(state.active)
    block[0] = min(vendor_mode, 10)
    block[1] = 1 if gaming_mode else 0
    if gaming_mode:
        block[2:5] = bytes(1 if flag else 0 for flag in disabled_keys)
    block[62:64] = protocol.BLOCK_TERMINATOR
    return bytes(block)


# -- vendor database import -------------------------------------------------


def _colorref_to_color(value: int) -> Color:
    """The vendor database stores Windows COLORREF values (0x00BBGGRR)."""
    return value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF


def state_from_gkdb(path: Path, profile: str | None = None, color_correction: bool = True) -> LightingState:
    """Rebuild the lighting state the vendor tool last wrote to the keyboard."""

    def device_color(value: int) -> Color:
        color = _colorref_to_color(value)
        return VENDOR_COLOR_CORRECTION.get(color, color) if color_correction else color

    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        if profile is None:
            row = connection.execute("SELECT Name FROM ProfileSummary WHERE IsActive = 1").fetchone()
            if row is None:
                raise ValueError("the database has no active profile")
            profile = row[0]
        row = connection.execute("SELECT KeyLightMode FROM ProfileSummary WHERE Name = ?", (profile,)).fetchone()
        if row is None:
            raise ValueError(f"profile {profile!r} not found")
        vendor_mode = row[0]

        state = LightingState()
        slot = vendor_mode - GKDB_FIRST_GENERIC_MODE
        if 0 <= slot < MODE_COUNT:
            state.active = MODE_NAMES[slot]
        elif vendor_mode == GKDB_CUSTOM_MODE:
            state.active = CUSTOM_MODE
        else:
            raise ValueError(f"unsupported KeyLightMode {vendor_mode}")

        query = (
            "SELECT LightMode, Direction, Frequency, Brightness, Color1, IsFullColor "
            "FROM KeyLightGeneral WHERE ProfileName = ?"
        )
        for light_mode, direction, frequency, brightness, color1, full_color in connection.execute(query, (profile,)):
            slot = light_mode - GKDB_FIRST_GENERIC_MODE
            if not 0 <= slot < MODE_COUNT:
                continue
            # The database stores slider positions (0..15), the wire uses 1..16.
            state.modes[MODE_NAMES[slot]] = ModeSettings(
                color=device_color(color1),
                full_color=bool(full_color),
                brightness=brightness + 1,
                speed=frequency + 1,
                direction=direction,
            )

        row = connection.execute(
            "SELECT Brightness FROM KeyLightCustomizationSummary WHERE ProfileName = ?", (profile,)
        ).fetchone()
        if row is not None:
            state.custom_brightness = row[0] + 1
        colors: list[Color] = [(0, 0, 0)] * MATRIX_SIZE
        query = "SELECT KeyIndex, Color FROM KeyLightCustomization WHERE ProfileName = ?"
        for key_index, color in connection.execute(query, (profile,)):
            if 0 <= key_index < MATRIX_SIZE:
                colors[key_index] = device_color(color)
        state.custom_colors = colors
    finally:
        connection.close()
    state.validate()
    return state


__all__ = [
    "CUSTOM_MODE", "LIGHTING_BLOCK_SIZE", "MATRIX_COLUMNS", "MATRIX_ROWS", "MODE_NAMES",
    "LightingState", "ModeSettings", "build_lighting_block", "build_profile_block",
    "default_state_path", "format_color", "parse_color", "resolve_mode", "state_from_gkdb",
]
