"""High level conversation with the keyboard."""

from __future__ import annotations

import logging
import os
import struct
from dataclasses import dataclass

from . import protocol
from .transport import HidTransport, Transport, precise_sleep

log = logging.getLogger(__name__)


class ProtocolError(Exception):
    """Raised when the keyboard answers in an unexpected way."""


@dataclass(frozen=True)
class DeviceInfo:
    raw: bytes
    macro_capacity_packets: int
    vendor_id: int
    product_id: int
    version: tuple[int, int]

    @classmethod
    def parse(cls, raw: bytes) -> "DeviceInfo":
        return cls(
            raw=raw,
            macro_capacity_packets=struct.unpack_from("<H", raw, 1)[0],
            vendor_id=struct.unpack_from("<H", raw, 4)[0],
            product_id=struct.unpack_from("<H", raw, 6)[0],
            version=(raw[8], raw[9]),
        )


class Keyboard:
    """Implements the command / data / checksum transaction scheme."""

    def __init__(self, transport: Transport, delay: float = 0.010, retries: int = 5) -> None:
        self.transport = transport
        self.delay = delay
        self.retries = retries
        self._authenticated = False

    @classmethod
    def open(cls, delay: float = 0.010) -> "Keyboard":
        return cls(HidTransport.open_first(), delay=delay)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "Keyboard":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- primitives ---------------------------------------------------------

    def _send(self, packet: bytes) -> None:
        log.debug("-> %s", packet.hex(" "))
        self.transport.send(packet)

    def _receive(self) -> bytes:
        packet = self.transport.receive()
        log.debug("<- %s", packet.hex(" "))
        return packet

    def _command(self, opcode: int, packet_count: int = 0, polls: int = 20, settle: float = 0.0) -> bytes:
        """Send a command and wait until the firmware acknowledges it.

        The firmware echoes the command with a status byte at offset 3:
        0x00 while it is still busy, 0x01 on success and 0xFF on failure.
        ``settle`` is an extra pause before the first poll, used by write
        commands to leave the firmware alone while it erases flash.
        """
        command = protocol.build_command(opcode, packet_count)
        last = b""
        for attempt in range(self.retries):
            self._send(command)
            precise_sleep(settle)
            for _ in range(polls):
                precise_sleep(self.delay)
                last = self._receive()
                prefix, echoed, status = protocol.parse_status(last)
                if prefix != protocol.COMMAND_PREFIX or echoed != opcode:
                    break
                if status == protocol.STATUS_OK:
                    return last
                if status == protocol.STATUS_ERROR:
                    break
            log.debug("command %02x attempt %d failed", opcode, attempt + 1)
        raise ProtocolError(f"command 04 {opcode:02x} was not acknowledged (last answer: {last[:8].hex(' ')})")

    def _finish(self, expected_checksum: int | None) -> int:
        answer = self._command(protocol.OP_CHECKSUM)
        reported = protocol.parse_checksum(answer)
        if expected_checksum is not None and reported != expected_checksum:
            raise ProtocolError(f"checksum mismatch: keyboard reported {reported:#x}, expected {expected_checksum:#x}")
        return reported

    def _send_payload(self, payload: bytes) -> None:
        for packet in protocol.split_packets(payload):
            self._send(packet)
            precise_sleep(self.delay)

    # -- operations ---------------------------------------------------------

    def read_info(self) -> DeviceInfo:
        """Read the 128 byte device information block.

        Unlike write commands the firmware replaces the acknowledgement with
        the first data packet almost immediately, so no ack is awaited here.
        """
        last_error: Exception | None = None
        for _ in range(self.retries):
            self._send(protocol.build_command(protocol.OP_READ_INFO, protocol.INFO_BLOCK_PACKETS))
            precise_sleep(self.delay)
            packets = []
            for _ in range(protocol.INFO_BLOCK_PACKETS):
                packets.append(self._receive())
                precise_sleep(self.delay)
            data = b"".join(packets)
            try:
                self._finish(protocol.checksum(data))
            except ProtocolError as exc:
                last_error = exc
                continue
            return DeviceInfo.parse(data)
        raise ProtocolError(f"could not read device info: {last_error}")

    def ping(self) -> bool:
        try:
            self._command(protocol.OP_PING)
        except ProtocolError:
            return False
        return True

    def authenticate(self, challenge: bytes | None = None) -> None:
        """Run the challenge / response check the vendor tool does before writes."""
        if challenge is None:
            challenge = os.urandom(protocol.PACKET_SIZE)
        self._command(protocol.OP_AUTH)
        self._send_payload(challenge)
        expected = protocol.auth_response(challenge)
        reported = self._finish(None)
        if reported != expected:
            raise ProtocolError(f"authentication failed: keyboard answered {reported:#010x}, expected {expected:#010x}")
        self._authenticated = True

    def write_block(self, opcode: int, payload: bytes) -> None:
        """Write one configuration block and verify its checksum.

        The USB id 05AC:024F is shared by many unrelated SONiX keyboards, so a
        write is only allowed after the firmware passed the vendor challenge.
        """
        if not self._authenticated:
            raise ProtocolError("refusing to write: the keyboard has not passed the firmware check (authenticate first)")
        payload = protocol.pad_to_packets(payload)
        # The vendor tool waits 35 ms per started 512 bytes for the flash erase.
        erase_time = ((len(payload) + 511) // 512) * 0.035
        self._command(opcode, len(payload) // protocol.PACKET_SIZE, settle=erase_time)
        self._send_payload(payload)
        self._finish(protocol.checksum(payload))

    def write_lighting(self, block: bytes) -> None:
        self.write_block(protocol.OP_WRITE_LIGHTING, block)

    def write_profile(self, block: bytes) -> None:
        self.write_block(protocol.OP_WRITE_PROFILE, block)

    def probe(self, opcode: int, reads: int = 3) -> list[bytes]:
        """Send a bare command and return what the feature report shows afterwards.

        Used for commands whose behaviour is unknown: nothing is assumed about
        the answer and nothing is retried.
        """
        self._send(protocol.build_command(opcode))
        answers = []
        for _ in range(reads):
            precise_sleep(self.delay)
            answers.append(self._receive())
        return answers

    def send_simple(self, opcode: int) -> None:
        """Send a command that the firmware never acknowledges (0xF0 / 0xF1)."""
        self._send(protocol.build_command(opcode))
        precise_sleep(self.delay)
