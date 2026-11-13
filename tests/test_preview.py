import pytest

from g87ctl.keys import KEY_POSITIONS
from g87ctl.lighting import CUSTOM_MODE, MODE_NAMES, LightingState, ModeSettings
from g87ctl.preview import EFFECTS, KEYS, LAYOUT_WIDTH, ROW_KEYS, frame, key_at


def test_layout_keys_are_unique_and_known():
    names = [key.name for key in KEYS]
    assert len(names) == len(set(names)) == 87
    assert all(name in KEY_POSITIONS for name in names)


def test_layout_rows_do_not_overlap():
    for keys in ROW_KEYS:
        end = 0
        for key in sorted(keys, key=lambda k: k.col):
            assert key.col >= end
            end = key.col + key.width
        assert end <= LAYOUT_WIDTH


def test_key_at_finds_keys_and_gaps():
    esc = next(key for key in KEYS if key.name == "esc")
    assert key_at(esc.row, esc.col) == "esc"
    assert key_at(esc.row, esc.col + esc.width - 1) is None  # the gap after the key
    assert key_at(99, 0) is None


def test_every_effect_has_a_model():
    assert set(EFFECTS) == set(MODE_NAMES)


@pytest.mark.parametrize("name", MODE_NAMES)
@pytest.mark.parametrize("full_color", [False, True])
def test_effect_colours_are_valid_over_time(name, full_color):
    state = LightingState()
    state.active = name
    state.modes[name] = ModeSettings(color=(10, 200, 30), full_color=full_color, speed=8, direction=2)
    for t in (0.0, 0.7, 3.3, 12.0):
        colors = frame(state, t)
        assert set(colors) == {key.name for key in KEYS}
        assert all(len(c) == 3 and all(0 <= v <= 255 and isinstance(v, int) for v in c) for c in colors.values())


def test_static_uses_colour_and_brightness():
    state = LightingState()
    state.modes["static"] = ModeSettings(color=(200, 100, 50), brightness=16)
    assert set(frame(state, 0.0).values()) == {(200, 100, 50)}
    state.modes["static"].brightness = 8
    assert set(frame(state, 0.0).values()) == {(100, 50, 25)}


def test_full_colour_static_varies_across_the_keyboard():
    state = LightingState()
    state.modes["static"].full_color = True
    assert len(set(frame(state, 0.0).values())) > 5


def test_breath_changes_over_time():
    state = LightingState()
    state.active = "breath"
    assert frame(state, 0.0) != frame(state, 1.5)


def test_custom_mode_is_static_and_scaled():
    state = LightingState()
    state.active = CUSTOM_MODE
    state.custom_brightness = 8
    state.custom_colors[KEYS[0].index] = (255, 0, 0)
    first = frame(state, 0.0)
    assert first[KEYS[0].name] == (128, 0, 0)
    assert frame(state, 5.0) == first
