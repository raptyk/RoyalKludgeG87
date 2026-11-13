"""Command line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, protocol
from .device import Keyboard, ProtocolError
from .keys import KEY_POSITIONS, key_index
from .lighting import (
    ACTIVE_RECORD_OFFSET,
    CUSTOM_MODE,
    MODE_NAMES,
    RECORD_SIZE,
    SLOT_COUNT,
    LightingState,
    ModeSettings,
    build_lighting_block,
    build_profile_block,
    default_state_path,
    encode_mode_record,
    format_color,
    parse_color,
    resolve_mode,
    state_from_gkdb,
)
from .transport import TransportError

OVERVIEW = """g87ctl {version} - lighting control for the GamingForce Z / Royal Kludge G87

usage: g87ctl [options] <command> [arguments]

commands
  set <effect> [opts]  pick an effect (name or 1-19)   g87ctl set breath --color 00ff00
  custom [opts]        per-key colours                 g87ctl custom --fill 000000 --key w=ff0000
  modes                list effects with stored settings (* = active)
  keys                 list key names for 'custom --key'
  apply                send the stored state again
  gui                  full-screen editor with an animated keyboard preview (needs textual)
  info                 show USB id and firmware version
  import-gkdb <file>   restore lighting from the vendor's GamingKeyboard.gkdb
  auth                 run the firmware check that guards every write
  experimental <what>  hidden firmware features, risky - see 'examples'
  examples             more examples, including hidden effects 20-32

set options     --color RRGGBB  --full-color  --brightness 1-16  --speed 1-16  --direction 0-3
custom options  --fill RRGGBB  --key NAME=RRGGBB (repeatable)  --brightness 1-16
global options  (before the command)  --dry-run  -v  --state FILE  --delay MS  --skip-profile
                -h shows this page, '<command> -h' shows details of one command

effects
{effects}

Writes go to the keyboard's flash; the state file ({state}) is the only record.
"""

EXAMPLES = """examples

  g87ctl set static --color ff0000                    red, everything else unchanged
  g87ctl set breath --color 00ff00 --speed 8          green breathing, speed 8
  g87ctl set 8 --brightness 12                        effect no. 8 (spectrum), dimmer
  g87ctl set colourful --full-color                   cycle through all colours

  g87ctl custom --fill 000000 --key w=ff0000          black keyboard, W in red
  g87ctl custom --key esc=ffffff --key f1=00ff00      change two keys, keep the rest

  g87ctl --dry-run set static --color ff0000          only print the data, send nothing
  g87ctl modes                                        what is stored right now
  g87ctl apply                                        send the stored state again

hidden effects 20-32 (risky, need 'experimental' and --yes)

  g87ctl experimental effect 20 --color ff0000 --brightness 16 --yes
  g87ctl apply                                        go back to the stored effect

colours are RRGGBB without '#'; brightness and speed are 1-16.
"""

EXPERIMENTAL_WARNING = """\
WARNING: experimental command.
This sends something the vendor driver contains but whose effect is unknown or
untested. It may change the keyboard's behaviour, and an unknown raw opcode may
erase part of its flash memory before any data arrives. There is no way to read
the configuration back. If the keyboard misbehaves, replug it and run
'g87ctl apply' (lighting) - key map and macros can only be restored with the
vendor tool.
"""

EXPERIMENTAL_OPCODES = {
    "ping": protocol.OP_PING,
    "cmd18": protocol.OP_UNKNOWN_18,
    "cmd19": protocol.OP_UNKNOWN_19,
    "cmdf0": protocol.OP_UNKNOWN_F0,
    "cmdf1": protocol.OP_UNKNOWN_F1,
}


def overview() -> str:
    names = [f"{number:2d} {name}" for number, name in enumerate(MODE_NAMES, start=1)]
    columns = 5
    rows = -(-len(names) // columns)
    lines = []
    for row in range(rows):
        cells = names[row::rows]
        lines.append("  " + "".join(f"{cell:<15}" for cell in cells).rstrip())
    return OVERVIEW.format(version=__version__, state=default_state_path(), effects="\n".join(lines))


def cmd_examples(args: argparse.Namespace) -> None:
    print(EXAMPLES, end="")


def _hex_dump(data: bytes) -> str:
    lines = []
    for offset in range(0, len(data), 16):
        lines.append(f"{offset:04x}  {data[offset:offset + 16].hex(' ')}")
    return "\n".join(lines)


def _open(args: argparse.Namespace) -> Keyboard:
    return Keyboard.open(delay=args.delay / 1000)


def _send_blocks(args: argparse.Namespace, lighting_block: bytes, profile_block: bytes) -> bool:
    """Send the blocks, or print them for --dry-run. Returns True when sent."""
    if args.dry_run:
        print("lighting block (command 04 13):")
        print(_hex_dump(lighting_block))
        print("profile block (command 04 17):")
        print(_hex_dump(profile_block))
        return False
    with _open(args) as keyboard:
        keyboard.authenticate()
        keyboard.write_lighting(lighting_block)
        keyboard.send_simple(protocol.OP_UNKNOWN_F0)
        if not args.skip_profile:
            keyboard.write_profile(profile_block)
    return True


def _apply(state: LightingState, args: argparse.Namespace) -> None:
    """Send the whole lighting state to the keyboard and persist it."""
    if _send_blocks(args, build_lighting_block(state), build_profile_block(state)):
        state.save(args.state)
        print(f"applied: {describe_active(state)}")


def _send_state(state: LightingState, args: argparse.Namespace) -> str:
    """Like _apply, but silent: returns a status line for the GUI."""
    if args.dry_run:
        build_lighting_block(state)  # validates the state
        return "dry run: nothing was sent"
    _send_blocks(args, build_lighting_block(state), build_profile_block(state))
    state.save(args.state)
    return f"applied: {describe_active(state)}"


def cmd_gui(args: argparse.Namespace) -> None:
    try:
        from .gui import run_gui
    except ImportError as exc:
        raise ValueError(f"the gui needs the 'textual' package (pip install g87ctl[gui]): {exc}") from exc
    run_gui(LightingState.load(args.state), lambda state: _send_state(state, args))


def describe_active(state: LightingState) -> str:
    if state.active == CUSTOM_MODE:
        return f"custom per-key colours, brightness {state.custom_brightness}"
    settings = state.modes[state.active]
    colour = "full colour" if settings.full_color else format_color(settings.color)
    return (
        f"{state.active} ({colour}, brightness {settings.brightness}, "
        f"speed {settings.speed}, direction {settings.direction})"
    )


def cmd_info(args: argparse.Namespace) -> None:
    with _open(args) as keyboard:
        info = keyboard.read_info()
    print(f"usb id:          {info.vendor_id:04x}:{info.product_id:04x}")
    print(f"firmware:        {info.version[0]}.{info.version[1]:02d}")
    print(f"macro capacity:  {info.macro_capacity_packets} packets ({info.macro_capacity_packets * 64} bytes)")
    print(f"raw:             {info.raw[:16].hex(' ')}")


def cmd_auth(args: argparse.Namespace) -> None:
    with _open(args) as keyboard:
        keyboard.authenticate()
    print("firmware check passed")


def cmd_modes(args: argparse.Namespace) -> None:
    state = LightingState.load(args.state)
    for number, name in enumerate(MODE_NAMES, start=1):
        marker = "*" if state.active == name else " "
        settings = state.modes[name]
        colour = "full colour" if settings.full_color else format_color(settings.color)
        print(
            f"{marker} {number:2d} {name:<11} {colour:<11} brightness {settings.brightness:2d} "
            f"speed {settings.speed:2d} direction {settings.direction}"
        )
    marker = "*" if state.active == CUSTOM_MODE else " "
    print(f"{marker}  - {CUSTOM_MODE:<11} per-key     brightness {state.custom_brightness:2d}")


def _update_settings(settings, args: argparse.Namespace) -> None:
    if args.color is not None:
        settings.color = parse_color(args.color)
        settings.full_color = False
    if args.full_color:
        settings.full_color = True
    if args.brightness is not None:
        settings.brightness = args.brightness
    if args.speed is not None:
        settings.speed = args.speed
    if args.direction is not None:
        settings.direction = args.direction


def cmd_set(args: argparse.Namespace) -> None:
    state = LightingState.load(args.state)
    name = resolve_mode(args.mode)
    if name == CUSTOM_MODE:
        raise ValueError("use the 'custom' command for per-key colours")
    _update_settings(state.modes[name], args)
    state.active = name
    _apply(state, args)


def cmd_custom(args: argparse.Namespace) -> None:
    state = LightingState.load(args.state)
    if args.fill is not None:
        state.custom_colors = [parse_color(args.fill)] * len(state.custom_colors)
    for assignment in args.key or []:
        name, separator, colour = assignment.rpartition("=")
        if not separator:
            raise ValueError(f"expected KEY=RRGGBB, got {assignment!r}")
        state.custom_colors[key_index(name)] = parse_color(colour)
    if args.brightness is not None:
        state.custom_brightness = args.brightness
    state.active = CUSTOM_MODE
    _apply(state, args)


def cmd_apply(args: argparse.Namespace) -> None:
    _apply(LightingState.load(args.state), args)


def cmd_import_gkdb(args: argparse.Namespace) -> None:
    state = state_from_gkdb(args.database, profile=args.profile, color_correction=not args.no_color_correction)
    if args.no_apply:
        state.save(args.state)
        print(f"imported into {args.state}: {describe_active(state)}")
        return
    _apply(state, args)


def cmd_keys(args: argparse.Namespace) -> None:
    cells = [f"{name} {row}_{column}" for name, (row, column) in KEY_POSITIONS.items()]
    for start in range(0, len(cells), 5):
        print("".join(f"{cell:<18}" for cell in cells[start : start + 5]).rstrip())


def _confirm_experimental(args: argparse.Namespace) -> None:
    print(EXPERIMENTAL_WARNING, file=sys.stderr)
    if args.yes or args.dry_run:
        return
    if not sys.stdin.isatty():
        raise ValueError("experimental commands need --yes when run non-interactively")
    answer = input("Type 'yes' to continue: ")
    if answer.strip().lower() != "yes":
        raise ValueError("aborted")


def _probe(args: argparse.Namespace, opcode: int) -> None:
    if args.dry_run:
        print(f"would send: {protocol.build_command(opcode)[:10].hex(' ')}")
        return
    with _open(args) as keyboard:
        keyboard.authenticate()
        answers = keyboard.probe(opcode)
    print(f"sent 04 {opcode:02x}; feature report afterwards:")
    for answer in answers:
        print(f"  {answer[:16].hex(' ')}")
    status = answers[-1][3] if answers[-1][1] == opcode else None
    meaning = {protocol.STATUS_OK: "acknowledged", protocol.STATUS_ERROR: "rejected", protocol.STATUS_PENDING: "no status"}
    print(f"result: {meaning.get(status, 'answer is not an echo of the command')}")


def cmd_experimental(args: argparse.Namespace) -> None:
    _confirm_experimental(args)
    if args.what in EXPERIMENTAL_OPCODES:
        _probe(args, EXPERIMENTAL_OPCODES[args.what])
    elif args.what == "raw":
        if args.value is None:
            raise ValueError("raw needs an opcode, for example: experimental raw e0")
        opcode = int(args.value, 16)
        if not 0 <= opcode <= 0xFF:
            raise ValueError("opcode must be one byte")
        _probe(args, opcode)
    elif args.what == "effect":
        if args.value is None or not args.value.isdigit() or not len(MODE_NAMES) < int(args.value) <= SLOT_COUNT:
            raise ValueError(f"effect needs a number from {len(MODE_NAMES) + 1} to {SLOT_COUNT}")
        effect_id = int(args.value)
        state = LightingState.load(args.state)
        settings = ModeSettings()
        _update_settings(settings, args)
        settings.validate()
        block = bytearray(build_lighting_block(state))
        record = encode_mode_record(effect_id, settings)
        slot_offset = (effect_id - 1) * RECORD_SIZE
        if effect_id - 1 != len(MODE_NAMES):  # slot 19 belongs to the custom mode
            block[slot_offset : slot_offset + RECORD_SIZE] = record
        block[ACTIVE_RECORD_OFFSET : ACTIVE_RECORD_OFFSET + RECORD_SIZE] = record
        if _send_blocks(args, bytes(block), build_profile_block(state)):
            print(f"sent hidden effect {effect_id}; the state file is unchanged, 'g87ctl apply' restores it")


def _add_effect_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--color", help="single colour as RRGGBB")
    parser.add_argument("--full-color", action="store_true", help="let the effect cycle through all colours")
    parser.add_argument("--brightness", type=int, help="1 to 16")
    parser.add_argument("--speed", type=int, help="1 to 16")
    parser.add_argument("--direction", type=int, help="0 to 3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="g87ctl", add_help=False, usage="g87ctl [options] <command> [arguments]")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--version", action="version", version=f"g87ctl {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--state", type=Path, default=default_state_path())
    parser.add_argument("--delay", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-profile", action="store_true")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("info", help="read the device information block").set_defaults(handler=cmd_info)
    commands.add_parser("auth", help="run the firmware challenge / response check").set_defaults(handler=cmd_auth)
    commands.add_parser("modes", help="list lighting modes and their stored settings").set_defaults(handler=cmd_modes)
    commands.add_parser("keys", help="list key names usable with 'custom --key'").set_defaults(handler=cmd_keys)
    commands.add_parser("examples", help="show usage examples").set_defaults(handler=cmd_examples)
    commands.add_parser("apply", help="send the stored lighting state again").set_defaults(handler=cmd_apply)
    commands.add_parser(
        "gui", help="full-screen editor with an animated keyboard preview (needs textual)"
    ).set_defaults(handler=cmd_gui)

    set_parser = commands.add_parser("set", help="select a built-in effect and optionally change it")
    set_parser.add_argument("mode", help="effect name or number (see 'modes')")
    _add_effect_options(set_parser)
    set_parser.set_defaults(handler=cmd_set)

    custom_parser = commands.add_parser("custom", help="per-key colours")
    custom_parser.add_argument("--fill", help="colour for every key as RRGGBB")
    custom_parser.add_argument("--key", action="append", metavar="KEY=RRGGBB", help="colour of one key, repeatable")
    custom_parser.add_argument("--brightness", type=int, help="1 to 16")
    custom_parser.set_defaults(handler=cmd_custom)

    import_parser = commands.add_parser("import-gkdb", help="load settings from the vendor tool's database")
    import_parser.add_argument("database", type=Path, help="path to GamingKeyboard.gkdb")
    import_parser.add_argument("--profile", help="profile name, defaults to the active one")
    import_parser.add_argument("--no-apply", action="store_true", help="only store the state, do not send it")
    import_parser.add_argument(
        "--no-color-correction", action="store_true", help="skip the vendor's colour substitution table"
    )
    import_parser.set_defaults(handler=cmd_import_gkdb)

    experimental_parser = commands.add_parser(
        "experimental",
        help="undocumented firmware features, at your own risk",
        description=EXPERIMENTAL_WARNING,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    experimental_parser.add_argument("what", choices=[*EXPERIMENTAL_OPCODES, "effect", "raw"])
    experimental_parser.add_argument("value", nargs="?", help="effect number (20-32) or raw opcode in hex")
    experimental_parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    _add_effect_options(experimental_parser)
    experimental_parser.set_defaults(handler=cmd_experimental)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.help or args.command is None:
        print(overview(), end="")
        return 0
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(message)s")
    try:
        args.handler(args)
    except (TransportError, ProtocolError, ValueError, KeyError, OSError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
