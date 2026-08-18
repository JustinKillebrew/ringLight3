"""Serial helpers for the classic Arduino running ringLight.ino."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import serial
from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

BAUD_RATE = 115200
BOOT_DELAY_S = 2.5

# Known USB vendor IDs for official Arduino boards and common clones.
# 0x2341 = Official Arduino
# 0x2A03 = Arduino.org
# 0x1A86 = CH340 (common clone UART)
# 0x0403 = FTDI (older boards/clones)
# 0x10C4 = Silicon Labs CP210x (some Nano clones)
# 0x239A = Adafruit
ARDUINO_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4, 0x239A}
OFFICIAL_VIDS = {0x2341, 0x2A03}

LINUX_BY_ID_HINTS = ("arduino", "ch340", "ftdi", "cp210", "usb-serial", "adafruit")
MAC_NAME_HINTS = ("usbmodem", "usbserial")
TEXT_HINTS = ("arduino", "ch340", "ftdi", "cp210", "adafruit")


def format_color_command(white: int, red: int, green: int, blue: int) -> str:
    """Build the LF-terminated protocol line used by ringLight.ino."""
    return f"W{int(white)},R{int(red)},G{int(green)},B{int(blue)}"


def _port_text(info: ListPortInfo) -> str:
    parts = [info.device, info.description, info.manufacturer, info.hwid]
    product = getattr(info, "product", None)
    serial_number = getattr(info, "serial_number", None)
    parts.extend([product, serial_number])
    return " ".join(part for part in parts if part).lower()


def _score_port(info: ListPortInfo) -> int | None:
    """Return a lower score for a better Arduino match, or None if rejected."""
    device = (info.device or "").lower()
    text = _port_text(info)
    vid = info.vid

    if sys.platform.startswith("linux") and device.startswith("/dev/ttyS"):
        return None
    if "bluetooth" in text:
        return None

    official = vid in OFFICIAL_VIDS or "arduino" in text
    known_vid = vid in ARDUINO_VIDS
    named = any(hint in text for hint in TEXT_HINTS)
    mac_usb = sys.platform == "darwin" and any(hint in device for hint in MAC_NAME_HINTS)

    if official:
        return 0
    if known_vid:
        return 1
    if named or mac_usb:
        return 2
    return None


def _linux_by_id_ports() -> list[str]:
    by_id = Path("/dev/serial/by-id")
    if not by_id.is_dir():
        return []

    matches = []
    for entry in sorted(by_id.iterdir()):
        name = entry.name.lower()
        if any(hint in name for hint in LINUX_BY_ID_HINTS):
            matches.append(str(entry.resolve()))
    return matches


def find_arduino_port() -> str | None:
    """Return the device path of a classic Arduino, or None if none is found."""
    if sys.platform.startswith("linux"):
        by_id = _linux_by_id_ports()
        if by_id:
            return by_id[0]

    ranked: list[tuple[int, str]] = []
    for info in list_ports.comports():
        score = _score_port(info)
        if score is not None:
            ranked.append((score, info.device))

    if not ranked:
        return None
    ranked.sort()
    return ranked[0][1]


class RingLight:
    """Open the Arduino serial port and send ringLight.ino commands."""

    def __init__(self, baud: int = BAUD_RATE, boot_delay_s: float = BOOT_DELAY_S):
        self.baud = baud
        self.boot_delay_s = boot_delay_s
        self.port: str | None = None
        self._ser: serial.Serial | None = None

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def connect(self, port: str | None = None) -> str:
        self.close(send_off=False)
        port = port or find_arduino_port()
        if not port:
            raise RuntimeError("No Arduino serial port found.")

        ser = serial.Serial(port, self.baud, timeout=1)
        # Opening the port toggles DTR and resets the Arduino; wait for boot.
        time.sleep(self.boot_delay_s)
        ser.reset_input_buffer()
        try:
            while ser.in_waiting:
                ser.readline()
        except OSError:
            pass

        self._ser = ser
        self.port = port
        return port

    def send_color(self, white: int, red: int, green: int, blue: int) -> str:
        cmd = format_color_command(white, red, green, blue)
        self._write(cmd)
        return cmd

    def send_off(self) -> None:
        self._write("OFF")

    def close(self, send_off: bool = True) -> None:
        if self._ser is None:
            return
        if send_off:
            try:
                self.send_off()
            except Exception:
                pass
        try:
            self._ser.close()
        except Exception:
            pass
        self._ser = None
        self.port = None

    def _write(self, line: str) -> None:
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Arduino is not connected.")
        self._ser.write(f"{line}\n".encode("ascii"))
        self._ser.flush()
