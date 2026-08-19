"""Serial helpers for the classic Arduino running ringLight.ino.

This module is the Python equivalent of findArduinoPort() and the serial
write helpers in ringLight_GUI.m. It:

  1. Finds a USB serial port that looks like an Arduino.
  2. Opens it at 115200 baud.
  3. Sends LF-terminated text commands: W#,R#,G#,B#  or  OFF.

Names that start with a single underscore (_score_port, _write, ...) are a
Python convention for "internal helper — not part of the public API."
"""

# from __future__ import annotations lets you write `str | None` type hints
# even on slightly older Python 3.10 interpreters. It is a no-op at runtime.
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import serial
from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

# Must match Serial.begin() in ringLight.ino.
BAUD_RATE = 115200

# Opening the serial port toggles DTR, which resets a classic Arduino.
# The sketch waits ~2 s in setup() before it is ready for commands.
BOOT_DELAY_S = 2.5

# USB vendor IDs. 0x means hexadecimal, same idea as MATLAB hex2dec('2341').
# 0x2341 = Official Arduino
# 0x2A03 = Arduino.org
# 0x1A86 = CH340 (common clone UART)
# 0x0403 = FTDI (older boards/clones)
# 0x10C4 = Silicon Labs CP210x (some Nano clones)
# 0x239A = Adafruit
ARDUINO_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4, 0x239A}
OFFICIAL_VIDS = {0x2341, 0x2A03}

# Substrings used when VID is missing and we have to guess from the device name.
LINUX_BY_ID_HINTS = ("arduino", "ch340", "ftdi", "cp210", "usb-serial", "adafruit")
MAC_NAME_HINTS = ("usbmodem", "usbserial")
TEXT_HINTS = ("arduino", "ch340", "ftdi", "cp210", "adafruit")


def format_color_command(white: int, red: int, green: int, blue: int) -> str:
    """Build the command string the Arduino sketch parses with sscanf.

    Example: format_color_command(100, 0, 0, 200) -> "W100,R0,G0,B200"

    The f-string (f"...") is Python's sprintf. {int(white)} means "insert
    this value, coerced to an integer."
    """
    return f"W{int(white)},R{int(red)},G{int(green)},B{int(blue)}"


def _decode_serial_text(raw: bytes) -> str:
    """Turn one serial read into printable text.

    Classic Arduinos often emit NUL bytes while the bootloader resets.
    """
    return raw.decode("ascii", errors="replace").replace("\x00", "").strip()


def _is_boot_banner(text: str) -> bool:
    """True for the sketch's one-time 'aiNeopixels serial server ready' line."""
    return "serial server ready" in text.lower()


def _drain_boot_banner(ser: serial.Serial) -> None:
    """Read and discard the ready line. Flush is not enough on Linux ACM.

    Opening the port resets the Uno, and the sketch prints one banner after
    delay(2000). The Arduino IDE Serial Monitor works because it already
    showed that line before you type a command.

    On /dev/ttyACM*, reset_input_buffer() (tcflush) often does not drop USB
    CDC data, and in_waiting stays 0 until you actually read. So we readline
    until we see the banner or a couple of empty timeouts.
    """
    old_timeout = ser.timeout
    ser.timeout = 0.25
    try:
        empty = 0
        for _ in range(20):
            text = _decode_serial_text(ser.readline())
            if _is_boot_banner(text):
                return
            if text:
                empty = 0
                continue
            empty += 1
            if empty >= 3:
                return
    except OSError:
        pass
    finally:
        ser.timeout = old_timeout


def _port_text(info: ListPortInfo) -> str:
    """Join all descriptive fields into one lowercase string for searching.

    pyserial's ListPortInfo is like a struct: .device, .description, .vid, ...
    getattr(info, "product", None) reads an optional field and returns None
    if that field does not exist, instead of crashing.
    """
    parts = [info.device, info.description, info.manufacturer, info.hwid]
    product = getattr(info, "product", None)
    serial_number = getattr(info, "serial_number", None)
    parts.extend([product, serial_number])
    # Skip empty/None entries, then lowercase so "Arduino" matches "arduino".
    return " ".join(part for part in parts if part).lower()


def _vid_from_info(info: ListPortInfo) -> int | None:
    """USB vendor ID, or None if this port has no USB identity.

    `int | None` is a type hint: "returns an int, or None."
    On Windows, pyserial sometimes leaves .vid empty but still puts
    VID:PID=2341:0043 into .hwid; the regex below scrapes that out.
    """
    if info.vid:
        return info.vid
    hwid = info.hwid or ""
    match = re.search(r"VID(?:[:_]PID[=:]|[_:])([0-9A-Fa-f]{4})", hwid, re.I)
    if match:
        # group(1) is the four hex digits; int(..., 16) parses hex -> integer.
        return int(match.group(1), 16)
    return None


def _score_port(info: ListPortInfo) -> int | None:
    """Rank a serial port. Lower score = better Arduino match. None = skip it.

    We reject built-in Linux ttyS* UARTs and Bluetooth COM ports, then prefer
    official Arduino VID/name over clone chips over a fuzzy name match.
    """
    device = (info.device or "").lower()
    text = _port_text(info)
    vid = _vid_from_info(info)

    # `device` is already lowercased, so built-in ttyS0 matches "/dev/ttys".
    if sys.platform.startswith("linux") and device.startswith("/dev/ttys"):
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
    """Linux: /dev/serial/by-id has stable names that include the USB product.

    Example symlink:
      usb-Arduino__www.arduino.cc__0043_... -> /dev/ttyACM0
    Path.resolve() follows that symlink to the real device node.
    """
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
    """Return the device path of a classic Arduino, or None if none is found.

    Linux prefers /dev/serial/by-id (same idea as findArduinoPort_linux in MATLAB).
    Everywhere else, walk pyserial's port list and pick the best score.
    """
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
    # sort() on (score, device) puts the lowest score first.
    ranked.sort()
    return ranked[0][1]


class RingLight:
    """Open the Arduino serial port and send ringLight.ino commands.

    One instance owns one serial.Serial connection. Methods map to the sketch:
      send_color(...) -> "W#,R#,G#,B#\\n"
      send_off()      -> "OFF\\n"
    """

    def __init__(self, baud: int = BAUD_RATE, boot_delay_s: float = BOOT_DELAY_S):
        self.baud = baud
        self.boot_delay_s = boot_delay_s
        self.port: str | None = None
        # Leading underscore: "please treat this as private."
        self._ser: serial.Serial | None = None

    @property
    def connected(self) -> bool:
        """True while the serial port is open. Used like a field: ring.connected."""
        return self._ser is not None and self._ser.is_open

    def connect(self, port: str | None = None) -> str:
        """Find (or use) a port, open it, wait for the Arduino reboot, return the name.

        `port = port or find_arduino_port()` means: if the caller passed a port,
        use it; otherwise auto-detect. In Python, None and "" are both "falsy."
        """
        self.close(send_off=False)
        port = port or find_arduino_port()
        if not port:
            raise RuntimeError("No Arduino serial port found.")

        ser = serial.Serial(port, self.baud, timeout=1)
        # Opening the port toggles DTR and resets the Arduino; wait for boot.
        time.sleep(self.boot_delay_s)
        _drain_boot_banner(ser)

        self._ser = ser
        self.port = port
        return port

    def send_color(self, white: int, red: int, green: int, blue: int) -> str:
        cmd = format_color_command(white, red, green, blue)
        self._write(cmd)
        return cmd

    def send_off(self) -> None:
        self._write("OFF")

    def readline(self) -> str:
        """Read one LF-terminated reply from the sketch.

        ringLight.ino answers with OK, OK OFF, or ERR.
        pyserial waits up to the port timeout (1 s). strip() removes the
        CR/LF that Arduino Serial.println adds.
        """
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Arduino is not connected.")
        # Skip bootloader NULs and a late ready-banner; those are not replies.
        for _ in range(5):
            text = _decode_serial_text(self._ser.readline())
            if not text or _is_boot_banner(text):
                continue
            return text
        return ""

    def close(self, send_off: bool = True) -> None:
        """Optionally send OFF, then release the port. Safe to call more than once."""
        if self._ser is None:
            return
        if send_off:
            try:
                self.send_off()
            except Exception:
                # Port may already be gone; still try to close the handle.
                pass
        try:
            self._ser.close()
        except Exception:
            pass
        self._ser = None
        self.port = None

    def _write(self, line: str) -> None:
        """Send one ASCII line with a Unix newline (LF), matching MATLAB writeline."""
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Arduino is not connected.")
        # encode("ascii") turns a Python str into bytes; serial ports speak bytes.
        self._ser.write(f"{line}\n".encode("ascii"))
        self._ser.flush()
