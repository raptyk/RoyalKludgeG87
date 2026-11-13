import sqlite3

import pytest

from g87ctl.keys import key_index
from g87ctl.lighting import (
    CUSTOM_MODE,
    LIGHTING_BLOCK_SIZE,
    LightingState,
    ModeSettings,
    build_lighting_block,
    build_profile_block,
    parse_color,
    resolve_mode,
    state_from_gkdb,
)


def test_block_size_and_default_records():
    block = build_lighting_block(LightingState())
    assert len(block) == LIGHTING_BLOCK_SIZE == 0x480
    assert block[0x00:0x10] == bytes.fromhex("010000ff0000000000100c000000aa55")
    assert block[0x120:0x130] == bytes.fromhex("130000ff0000000000100c000000aa55")
    assert block[0x130:0x140] == bytes.fromhex("800000000000000000100000 0000aa55")
    assert not any(block[0x140:0x200])
    assert block[0x200:0x204] == bytes.fromhex("80000000")
    assert block[0x440:0x450] == block[0x00:0x10]
    assert not any(block[0x450:])


def test_mode_record_fields():
    state = LightingState()
    state.modes["glittering"] = ModeSettings(color=(1, 2, 3), full_color=True, brightness=5, speed=7, direction=2)
    state.active = "glittering"
    block = build_lighting_block(state)
    record = bytes.fromhex("0401020300000000010507020000aa55")
    assert block[0x30:0x40] == record
    assert block[0x440:0x450] == record


def test_custom_mode_block():
    state = LightingState()
    state.active = CUSTOM_MODE
    state.custom_brightness = 9
    state.custom_colors[key_index("esc")] = parse_color("ff8000")
    block = build_lighting_block(state)
    assert block[0x440:0x450] == bytes.fromhex("800000000000000000090000 0000aa55")
    offset = 0x200 + key_index("esc") * 4
    assert block[offset : offset + 4] == bytes.fromhex("80ff8000")


def test_profile_block():
    state = LightingState()
    assert build_profile_block(state)[:5] == bytes([9, 0, 0, 0, 0])
    state.active = "colourful"
    block = build_profile_block(state)
    assert block[0] == 10
    assert block[62:] == b"\xaa\x55"
    assert len(block) == 64


def test_validation_rejects_out_of_range_levels():
    state = LightingState()
    state.modes["static"].brightness = 17
    with pytest.raises(ValueError):
        build_lighting_block(state)


def test_resolve_mode():
    assert resolve_mode("1") == "static"
    assert resolve_mode("Shuttle") == "shuttle"
    with pytest.raises(ValueError):
        resolve_mode("20")


def test_key_index():
    assert key_index("Esc") == 1
    assert key_index("Left Shift".replace("Left ", "l")) == 4 * 18 + 1
    assert key_index("7_17") == 143
    with pytest.raises(KeyError):
        key_index("nope")


def test_json_round_trip():
    state = LightingState()
    state.active = "breath"
    state.modes["breath"].color = (10, 20, 30)
    state.custom_colors[5] = (1, 2, 3)
    restored = LightingState.from_json(state.to_json())
    assert build_lighting_block(restored) == build_lighting_block(state)


def test_import_from_vendor_database(tmp_path):
    path = tmp_path / "GamingKeyboard.gkdb"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE ProfileSummary(Name TEXT, IsUsed INT, IsActive INT, KeyLightMode INT,
                                    IsGamingModeEnabled INT, BindHotKeyIndex INT);
        CREATE TABLE KeyLightGeneral(ProfileName TEXT, LightMode INT, Direction INT, Frequency INT,
                                     Brightness INT, Color1 INT, Color2 INT, IsFullColor INT);
        CREATE TABLE KeyLightCustomizationSummary(ProfileName TEXT, Brightness INT);
        CREATE TABLE KeyLightCustomization(ProfileName TEXT, KeyIndex INT, Color INT);
        INSERT INTO ProfileSummary VALUES ('Profile0', 0, 1, 14, 0, -1);
        INSERT INTO KeyLightGeneral VALUES ('Profile0', 14, 1, 1, 15, 16711680, 0, 0);
        INSERT INTO KeyLightGeneral VALUES ('Profile0', 9, 0, 11, 7, 255, 0, 1);
        INSERT INTO KeyLightCustomizationSummary VALUES ('Profile0', 3);
        INSERT INTO KeyLightCustomization VALUES ('Profile0', 1, 65280);
        """
    )
    connection.commit()
    connection.close()

    state = state_from_gkdb(path)
    assert state.active == "colourful"
    # Pure blue goes through the vendor colour correction table.
    assert state.modes["colourful"] == ModeSettings((0x30, 0x80, 0xFF), False, 16, 2, 1)
    assert state.modes["static"] == ModeSettings((255, 0, 0), True, 8, 12, 0)
    assert state.custom_brightness == 4
    assert state.custom_colors[1] == (0, 255, 0)

    uncorrected = state_from_gkdb(path, color_correction=False)
    assert uncorrected.modes["colourful"].color == (0, 0, 255)
