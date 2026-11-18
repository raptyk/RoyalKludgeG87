import pytest

pytest.importorskip("textual")

from textual.widgets import Input, OptionList

from g87ctl.tui import G87App, KeyboardPreview, render_keyboard
from g87ctl.lighting import CUSTOM_MODE, LightingState
from g87ctl.preview import KEYS, ROWS, frame


def test_render_keyboard_has_one_line_per_row():
    text = render_keyboard(frame(LightingState(), 0.0), selected="esc")
    assert len(text.plain.split("\n")) == ROWS
    assert "Esc" in text.plain
    assert sum(1 for span in text.spans if span.style.reverse) == 1  # only the selected key


@pytest.mark.asyncio
async def test_editing_a_field_updates_the_state():
    state = LightingState()
    app = G87App(state, lambda s: "sent")
    async with app.run_test(size=(100, 36)) as pilot:
        await pilot.pause()
        app.query_one("#color", Input).value = "00ff00"
        app.query_one("#brightness", Input).value = "5"
        await pilot.pause()
        assert state.modes["static"].color == (0, 255, 0)
        assert state.modes["static"].brightness == 5
        app.query_one("#brightness", Input).value = "99"  # out of range: ignored
        await pilot.pause()
        assert state.modes["static"].brightness == 5


@pytest.mark.asyncio
async def test_custom_mode_edits_the_selected_key_and_sends():
    state = LightingState()
    sent = []
    app = G87App(state, lambda s: sent.append(s.active) or "applied")
    async with app.run_test(size=(100, 36)) as pilot:
        await pilot.pause()
        app.query_one("#effects", OptionList).highlighted = 19  # custom
        await pilot.pause()
        assert state.active == CUSTOM_MODE
        app.post_message(KeyboardPreview.KeyClicked("w"))
        await pilot.pause()
        app.query_one("#color", Input).value = "ff0000"
        await pilot.pause()
        key = next(key for key in KEYS if key.name == "w")
        assert state.custom_colors[key.index] == (255, 0, 0)
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        assert sent == [CUSTOM_MODE]
