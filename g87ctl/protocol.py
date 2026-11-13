"""Wire-level constants and pure helpers for the GamingForce Z / RK G87 protocol.

Everything here is side-effect free so it can be unit tested without a keyboard.
See docs/PROTOCOL.md for the full description.
"""

from __future__ import annotations

import struct

PACKET_SIZE = 64

# USB identifiers. The vendor shipped two builds of the driver: the original
# looked for a genuine SONiX id, the later one for a keyboard that reports
# Apple's id (a common trick on SONiX based boards).
KNOWN_DEVICE_IDS: tuple[tuple[int, int], ...] = (
    (0x05AC, 0x024F),
    (0x0C45, 0x7A04),
)

# The 64 byte feature report lives on the boot keyboard interface.
CONTROL_INTERFACE = 0
# Vendor collection that emits 3 byte notifications (report id 5).
NOTIFY_USAGE_PAGE = 0xFFFF

COMMAND_PREFIX = 0x04

# Opcodes (second byte of a command packet).
OP_CHECKSUM = 0x02  # finish a transfer, returns the checksum of its payload
OP_READ_INFO = 0x05  # read the device information block
OP_WRITE_KEYMAP = 0x11
OP_WRITE_LIGHTING = 0x13
OP_WRITE_MACROS = 0x15
OP_WRITE_PROFILE = 0x17
OP_UNKNOWN_18 = 0x18  # sent by the vendor tool with a boolean "true"
OP_UNKNOWN_19 = 0x19  # sent by the vendor tool with a boolean "false"
OP_AUTH = 0xAB  # challenge / response check of the firmware
OP_PING = 0xE0  # "is the device alive", only acknowledged
OP_UNKNOWN_F0 = 0xF0  # sent after a lighting write (apply / leave sync mode)
OP_UNKNOWN_F1 = 0xF1  # counterpart of 0xF0, never acknowledged

STATUS_PENDING = 0x00
STATUS_OK = 0x01
STATUS_ERROR = 0xFF

BLOCK_TERMINATOR = b"\xaa\x55"  # little endian 0x55AA closing most records

AUTH_XOR_KEY = 0x54711688

INFO_BLOCK_PACKETS = 2


def build_command(opcode: int, packet_count: int = 0) -> bytes:
    """Return a 64 byte command packet.

    Layout: 04 <opcode> 00 00 00 00 00 00 <count lo> <count hi> 00...
    """
    if not 0 <= opcode <= 0xFF:
        raise ValueError("opcode out of range")
    if not 0 <= packet_count <= 0xFFFF:
        raise ValueError("packet count out of range")
    packet = bytearray(PACKET_SIZE)
    packet[0] = COMMAND_PREFIX
    packet[1] = opcode
    struct.pack_into("<H", packet, 8, packet_count)
    return bytes(packet)


def pad_to_packets(data: bytes) -> bytes:
    """Zero pad a payload to a whole number of 64 byte packets."""
    remainder = len(data) % PACKET_SIZE
    if remainder:
        data = data + bytes(PACKET_SIZE - remainder)
    return data


def split_packets(data: bytes) -> list[bytes]:
    data = pad_to_packets(data)
    return [data[i : i + PACKET_SIZE] for i in range(0, len(data), PACKET_SIZE)]


def checksum(data: bytes) -> int:
    """Checksum reported by OP_CHECKSUM: plain 32 bit sum of all payload bytes."""
    return sum(data) & 0xFFFFFFFF


def auth_response(challenge: bytes) -> int:
    """Value the firmware returns for a 64 byte OP_AUTH challenge."""
    if len(challenge) != PACKET_SIZE:
        raise ValueError("challenge must be exactly 64 bytes")
    b3 = (challenge[0x0C] + challenge[0x03]) & 0xFF
    b2 = (challenge[0x3F] << 3) & 0xFF
    b1 = (challenge[0x06] - challenge[0x0D]) & 0xFF
    b0 = challenge[0x24] & 0xA5
    return ((b3 << 24) | (b2 << 16) | (b1 << 8) | b0) ^ AUTH_XOR_KEY


def parse_status(response: bytes) -> tuple[int, int, int]:
    """Split a command response into (prefix, opcode, status)."""
    return response[0], response[1], response[3]


def parse_checksum(response: bytes) -> int:
    return struct.unpack_from("<I", response, 4)[0]
