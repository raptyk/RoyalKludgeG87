"""Full-screen terminal UI with an animated keyboard preview (needs 'textual')."""

from __future__ import annotations

import copy
from collections.abc import Callable

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.widgets import Checkbox, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .keys import key_index
from .lighting import CUSTOM_MODE, MATRIX_SIZE, MODE_NAMES, Color, LightingState, format_color, parse_color
from .preview import LAYOUT_WIDTH, ROW_KEYS, ROWS, frame, key_at

FPS = 15
OFF_FLOOR = 28  # unlit keys are drawn dark grey so that they stay visible

SendState = Callable[[LightingState], str]


def _visible(color: Color) -> Color:
    """Map 0..255 to OFF_FLOOR..255 so that a black key is still drawn."""
    return tuple(round(OFF_FLOOR + c * (255 - OFF_FLOOR) / 255) for c in color)  # type: ignore[return-value]


def _text_color(background: Color) -> str:
    luminance = 0.299 * background[0] + 0.587 * background[1] + 0.114 * background[2]
    return "#000000" if luminance > 140 else "#ffffff"


def render_keyboard(colors: dict[str, Color], selected: str | None = None) -> Text:
    """Draw the keyboard as styled text, one terminal line per key row."""
    text = Text(no_wrap=True)
    for row in range(ROWS):
        column = 0
        for key in ROW_KEYS[row]:
            text.append(" " * (key.col - column))
            column = key.col + key.width
            background = _visible(colors[key.name])
            body = key.label.center(key.width - 1)
            is_selected = key.name == selected
            style = Style(
                color=_text_color(background),
                bgcolor="#%02x%02x%02x" % background,
                bold=is_selected,
                underline=is_selected,
                reverse=is_selected,
            )
            text.append(body, style)
            text.append(" ")
        if row < ROWS - 1:
            text.append("\n")
    return text


class KeyboardPreview(Static):
    """The animated keyboard; clicking a key reports its name."""

    class KeyClicked(Message):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    def on_click(self, event: Click) -> None:
        name = key_at(event.y, event.x)
        if name is not None:
            self.post_message(self.KeyClicked(name))


class G87App(App[None]):
    TITLE = "g87ctl"
    SUB_TITLE = "GamingForce Z / Royal Kludge G87"

    CSS = f"""
    #preview-box {{ height: {ROWS + 2}; align: center middle; border: round $primary; }}
    KeyboardPreview {{ width: {LAYOUT_WIDTH}; height: {ROWS}; }}
    #main {{ height: 1fr; }}
    #effects {{ width: 30; }}
    #settings {{ padding: 1 2; }}
    .row {{ height: 1; margin-bottom: 1; }}
    .row Label {{ width: 18; }}
    .row Input {{ width: 14; height: 1; border: none; padding: 0 1; }}
    .row Input.invalid {{ background: $error 50%; }}
    Checkbox {{ border: none; height: 1; padding: 0; margin-bottom: 1; }}
    #hint {{ color: $text-muted; }}
    #status {{ height: 1; padding: 0 1; }}
    """

    BINDINGS = [
        Binding("ctrl+s", "apply", "Send to keyboard"),
        Binding("ctrl+f", "fill", "Fill all keys (custom)"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, state: LightingState, send: SendState) -> None:
        super().__init__()
        self.state = state
        self._send = send
        self._selected_key = "esc"
        self._time = 0.0

    # -- layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="preview-box"):
            yield KeyboardPreview(id="preview")
        with Horizontal(id="main"):
            options = [Option(f"{number:2d} {name}", id=name) for number, name in enumerate(MODE_NAMES, start=1)]
            options.append(Option("   custom (per key)", id=CUSTOM_MODE))
            yield OptionList(*options, id="effects")
            with Vertical(id="settings"):
                with Horizontal(classes="row"):
                    yield Label("Colour RRGGBB", id="color-label")
                    yield Input(id="color", max_length=7)
                yield Checkbox("Full colour", id="full")
                with Horizontal(classes="row"):
                    yield Label("Brightness 1-16")
                    yield Input(id="brightness", max_length=2)
                with Horizontal(classes="row"):
                    yield Label("Speed 1-16")
                    yield Input(id="speed", max_length=2)
                with Horizontal(classes="row"):
                    yield Label("Direction 0-3")
                    yield Input(id="direction", max_length=1)
                yield Static(id="hint")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        effects = self.query_one("#effects", OptionList)
        names = [*MODE_NAMES, CUSTOM_MODE]
        effects.highlighted = names.index(self.state.active)
        effects.focus()
        self._load_fields()
        self.set_interval(1 / FPS, self._tick)

    # -- animation --------------------------------------------------------------

    def _tick(self) -> None:
        self._time += 1 / FPS
        selected = self._selected_key if self.state.active == CUSTOM_MODE else None
        self.query_one("#preview", KeyboardPreview).update(render_keyboard(frame(self.state, self._time), selected))

    # -- state <-> widgets ------------------------------------------------------

    @property
    def _custom(self) -> bool:
        return self.state.active == CUSTOM_MODE

    def _load_fields(self) -> None:
        """Copy the stored values of the current mode into the input widgets."""
        custom = self._custom
        if custom:
            color = self.state.custom_colors[key_index(self._selected_key)]
            brightness = self.state.custom_brightness
            hint = f"Click a key in the preview to select it ({self._selected_key}); Ctrl+F fills all keys."
        else:
            settings = self.state.modes[self.state.active]
            color, brightness = settings.color, settings.brightness
            hint = "Edits are previewed at once; Ctrl+S sends them to the keyboard."
            self.query_one("#full", Checkbox).value = settings.full_color
            self.query_one("#speed", Input).value = str(settings.speed)
            self.query_one("#direction", Input).value = str(settings.direction)
        self.query_one("#color", Input).value = format_color(color)
        self.query_one("#brightness", Input).value = str(brightness)
        for widget_id in ("#full", "#speed", "#direction"):
            self.query_one(widget_id).disabled = custom
        self.query_one("#hint", Static).update(hint)

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(Text(message))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.state.active = event.option.id
        self._load_fields()

    def on_keyboard_preview_key_clicked(self, message: KeyboardPreview.KeyClicked) -> None:
        self._selected_key = message.name
        if self._custom:
            self._load_fields()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if not self._custom:
            self.state.modes[self.state.active].full_color = event.value

    def on_input_changed(self, event: Input.Changed) -> None:
        """Apply a valid edit; an invalid one is only marked, never stored."""
        field = event.input.id
        try:
            if field == "color":
                self._edit_color(parse_color(event.value))
            else:
                self._edit_number(field, int(event.value))
        except ValueError:
            event.input.add_class("invalid")
        else:
            event.input.remove_class("invalid")

    def _edit_color(self, color: Color) -> None:
        if self._custom:
            self.state.custom_colors[key_index(self._selected_key)] = color
            return
        settings = self.state.modes[self.state.active]
        if color != settings.color:
            settings.color = color
            if settings.full_color:
                settings.full_color = False
                self.query_one("#full", Checkbox).value = False

    def _edit_number(self, field: str, value: int) -> None:
        upper = {"brightness": 16, "speed": 16, "direction": 3}[field]
        lower = 0 if field == "direction" else 1
        if not lower <= value <= upper:
            raise ValueError(f"{field} must be between {lower} and {upper}")
        if field == "brightness" and self._custom:
            self.state.custom_brightness = value
        elif not self._custom:
            setattr(self.state.modes[self.state.active], field, value)

    # -- actions ----------------------------------------------------------------

    def action_fill(self) -> None:
        if not self._custom:
            self._set_status("Fill works in the custom mode only")
            return
        try:
            color = parse_color(self.query_one("#color", Input).value)
        except ValueError as exc:
            self._set_status(f"error: {exc}")
            return
        self.state.custom_colors = [color] * MATRIX_SIZE
        self._set_status(f"all keys set to {format_color(color)}")

    def action_apply(self) -> None:
        self._set_status("sending...")
        self._send_in_background(copy.deepcopy(self.state))

    @work(thread=True, exclusive=True)
    def _send_in_background(self, snapshot: LightingState) -> None:
        try:
            message = self._send(snapshot)
        except Exception as exc:  # any failure is shown to the user, not raised
            message = f"error: {exc}"
        self.call_from_thread(self._set_status, message)


def run_gui(state: LightingState, send: SendState) -> None:
    """Open the UI; 'send' writes a state to the keyboard and returns a status line."""
    G87App(state, send).run()
