"""HID feature report transport."""

from __future__ import annotations

import time
from typing import Protocol

from . import protocol


class TransportError(Exception):
    """Raised when the keyboard cannot be reached or rejects a report."""


def _load_hidapi():
    try:
        import hid
    except ImportError as exc:
        raise TransportError("the 'hidapi' package is missing, install it with: python -m pip install hidapi") from exc
    return hid


class Transport(Protocol):
    def send(self, packet: bytes) -> None: ...

    def receive(self) -> bytes: ...

    def close(self) -> None: ...


class HidTransport:
    """Talks to the keyboard through 64 byte HID feature reports (report id 0).

    The feature report belongs to the boot keyboard interface. Windows keeps
    that interface open exclusively, but feature reports still work on a handle
    opened without read/write access, which is what hidapi falls back to.
    """

    def __init__(self, path: bytes, vendor_id: int, product_id: int) -> None:
        hid = _load_hidapi()

        self.path = path
        self.vendor_id = vendor_id
        self.product_id = product_id
        self._device = hid.device()
        try:
            self._device.open_path(path)
        except OSError as exc:
            raise TransportError(f"cannot open HID device: {exc}") from exc

    @classmethod
    def find(cls) -> list[dict]:
        """Return hidapi descriptors of every supported control interface."""
        hid = _load_hidapi()

        found = []
        for vendor_id, product_id in protocol.KNOWN_DEVICE_IDS:
            for info in hid.enumerate(vendor_id, product_id):
                if info["interface_number"] != protocol.CONTROL_INTERFACE:
                    continue
                # Linux reports usage_page 0 without hidraw parsing support.
                if info["usage_page"] not in (0, 1):
                    continue
                found.append(info)
        return found

    @classmethod
    def open_first(cls) -> "HidTransport":
        candidates = cls.find()
        if not candidates:
            ids = ", ".join(f"{v:04X}:{p:04X}" for v, p in protocol.KNOWN_DEVICE_IDS)
            raise TransportError(f"no supported keyboard found (looked for {ids})")
        info = candidates[0]
        return cls(info["path"], info["vendor_id"], info["product_id"])

    def send(self, packet: bytes) -> None:
        if len(packet) != protocol.PACKET_SIZE:
            raise ValueError("packet must be exactly 64 bytes")
        written = self._device.send_feature_report(b"\x00" + packet)
        if written < 0:
            raise TransportError(f"set feature failed: {self._device.error()}")

    def receive(self) -> bytes:
        try:
            report = bytes(self._device.get_feature_report(0, protocol.PACKET_SIZE + 1))
        except OSError as exc:
            raise TransportError(f"get feature failed: {exc}") from exc
        if len(report) == protocol.PACKET_SIZE + 1:
            report = report[1:]
        if len(report) != protocol.PACKET_SIZE:
            raise TransportError(f"unexpected feature report length {len(report)}")
        return report

    def close(self) -> None:
        self._device.close()


def precise_sleep(seconds: float) -> None:
    """Sleep that stays accurate for the few milliseconds the protocol needs."""
    if seconds <= 0:
        return
    deadline = time.perf_counter() + seconds
    if seconds > 0.02:
        time.sleep(seconds - 0.01)
    while time.perf_counter() < deadline:
        pass
