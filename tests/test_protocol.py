import pytest

from g87ctl import protocol
from g87ctl.device import DeviceInfo, Keyboard, ProtocolError

# Information block captured from a real keyboard (firmware 1.01).
INFO_BLOCK = bytes.fromhex("40300000ac054f020101ffff").ljust(128, b"\0")


class FakeKeyboardFirmware:
    """Minimal model of the firmware side of the transaction scheme."""

    def __init__(self) -> None:
        self.buffer = bytes(protocol.PACKET_SIZE)
        self.pending_packets = 0
        self.received = bytearray()
        self.read_queue: list[bytes] = []
        self.sum = 0
        self.auth = False
        self.writes: dict[int, bytes] = {}
        self.opcode = 0

    def send(self, packet: bytes) -> None:
        if self.pending_packets:
            self.received += packet
            self.sum += sum(packet)
            self.pending_packets -= 1
            if not self.pending_packets and not self.auth:
                self.writes[self.opcode] = bytes(self.received)
            return
        opcode = packet[1]
        answer = bytearray(packet)
        answer[3] = protocol.STATUS_OK
        if opcode == protocol.OP_CHECKSUM:
            value = protocol.auth_response(bytes(self.received)) if self.auth else self.sum
            answer[4:8] = value.to_bytes(4, "little")
            self.auth = False
        elif opcode == protocol.OP_READ_INFO:
            self.sum = sum(INFO_BLOCK)
            self.read_queue = protocol.split_packets(INFO_BLOCK)
        else:
            self.opcode = opcode
            self.sum = 0
            self.received = bytearray()
            self.auth = opcode == protocol.OP_AUTH
            self.pending_packets = 1 if self.auth else packet[8] | (packet[9] << 8)
        self.buffer = bytes(answer)

    def receive(self) -> bytes:
        if self.read_queue:
            return self.read_queue.pop(0)
        return self.buffer

    def close(self) -> None:
        pass


def make_keyboard() -> tuple[Keyboard, FakeKeyboardFirmware]:
    firmware = FakeKeyboardFirmware()
    return Keyboard(firmware, delay=0), firmware


def test_build_command_layout():
    packet = protocol.build_command(protocol.OP_WRITE_LIGHTING, 18)
    assert len(packet) == 64
    assert packet[:10] == bytes.fromhex("04130000000000001200")
    assert not any(packet[10:])


def test_checksum_matches_captured_info_block():
    assert protocol.checksum(INFO_BLOCK) == 0x372


def test_auth_response_formula():
    challenge = bytearray(64)
    challenge[0x03] = 0xF0
    challenge[0x0C] = 0x20  # (0xF0 + 0x20) & 0xFF = 0x10
    challenge[0x3F] = 0x21  # (0x21 << 3) & 0xFF = 0x08
    challenge[0x06] = 0x01
    challenge[0x0D] = 0x03  # (1 - 3) & 0xFF = 0xFE
    challenge[0x24] = 0xFF  # & 0xA5 = 0xA5
    assert protocol.auth_response(bytes(challenge)) == 0x1008FEA5 ^ 0x54711688


def test_pad_and_split():
    packets = protocol.split_packets(b"\x01" * 65)
    assert [len(p) for p in packets] == [64, 64]
    assert packets[1] == b"\x01" + bytes(63)


def test_read_info():
    keyboard, _ = make_keyboard()
    info = keyboard.read_info()
    assert isinstance(info, DeviceInfo)
    assert (info.vendor_id, info.product_id) == (0x05AC, 0x024F)
    assert info.version == (1, 1)
    assert info.macro_capacity_packets == 0x30


def test_write_requires_authentication():
    keyboard, firmware = make_keyboard()
    with pytest.raises(ProtocolError):
        keyboard.write_lighting(bytes(0x480))
    assert not firmware.writes


def test_authenticated_write_reaches_the_firmware():
    keyboard, firmware = make_keyboard()
    keyboard.authenticate()
    payload = bytes(range(256)) * 4 + bytes(0x80)
    keyboard.write_lighting(payload)
    assert firmware.writes[protocol.OP_WRITE_LIGHTING] == payload


def test_wrong_firmware_fails_authentication():
    keyboard, firmware = make_keyboard()
    original_send = firmware.send

    def tampering_send(packet: bytes) -> None:
        original_send(packet)
        if packet[1] == protocol.OP_CHECKSUM:
            firmware.buffer = firmware.buffer[:4] + bytes(4) + firmware.buffer[8:]

    firmware.send = tampering_send
    with pytest.raises(ProtocolError):
        keyboard.authenticate(bytes(range(64)))
    with pytest.raises(ProtocolError):
        keyboard.write_lighting(bytes(64))
