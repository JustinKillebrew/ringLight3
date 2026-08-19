"""Unit tests for serial protocol and Arduino port detection."""

from unittest.mock import MagicMock, patch

import pytest

from serial.tools.list_ports_common import ListPortInfo

import arduino
from arduino import (
    BAUD_RATE,
    RingLight,
    _linux_by_id_ports,
    _score_port,
    _vid_from_info,
    find_arduino_port,
    format_color_command,
)


def make_port(
    device: str,
    *,
    vid: int | None = None,
    description: str = "n/a",
    manufacturer: str | None = None,
    hwid: str = "n/a",
    product: str | None = None,
    serial_number: str | None = None,
) -> ListPortInfo:
    """Build a pyserial port record without touching the real device node."""
    info = ListPortInfo(device, skip_link_detection=True)
    info.vid = vid
    info.description = description
    info.manufacturer = manufacturer
    info.hwid = hwid
    info.product = product
    info.serial_number = serial_number
    return info


class FakeSerial:
    """In-memory stand-in for pyserial's Serial so tests never open a port."""

    def __init__(self, port, baud, timeout=1):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.is_open = True
        self.written = bytearray()
        self.in_waiting = 0
        self.banner_lines = []
        self.reset_calls = 0
        self.closed = False
        self.readline_error = None

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        self.reset_calls += 1

    def readline(self) -> bytes:
        if self.readline_error is not None:
            raise self.readline_error
        if self.banner_lines:
            line = self.banner_lines.pop(0)
            if not self.banner_lines:
                self.in_waiting = 0
            return line
        self.in_waiting = 0
        return b""

    def close(self) -> None:
        self.is_open = False
        self.closed = True


@pytest.mark.parametrize(
    ("white", "red", "green", "blue", "expected"),
    [
        (0, 0, 0, 0, "W0,R0,G0,B0"),
        (100, 0, 0, 200, "W100,R0,G0,B200"),
        (255, 255, 255, 255, "W255,R255,G255,B255"),
        (128, 64, 32, 0, "W128,R64,G32,B0"),
        (10.7, 1.2, 2.9, 3.1, "W10,R1,G2,B3"),
    ],
)
def test_format_color_command(white, red, green, blue, expected):
    assert format_color_command(white, red, green, blue) == expected


def test_vid_from_info_uses_vid_field():
    info = make_port("/dev/ttyACM0", vid=0x2341)
    assert _vid_from_info(info) == 0x2341


def test_vid_from_info_parses_windows_hwid():
    info = make_port(
        "COM3",
        hwid="USB VID:PID=2341:0043 SER=ABC LOCATION=1-1",
    )
    assert _vid_from_info(info) == 0x2341


def test_vid_from_info_parses_underscore_hwid():
    info = make_port("COM4", hwid="VID_1A86&PID_7523")
    assert _vid_from_info(info) == 0x1A86


def test_vid_from_info_returns_none_when_missing():
    info = make_port("/dev/ttyUSB0", hwid="n/a")
    assert _vid_from_info(info) is None


def test_score_prefers_official_arduino_vid():
    info = make_port("/dev/ttyACM0", vid=0x2341, description="Arduino Uno")
    assert _score_port(info) == 0


def test_score_prefers_arduino_name_without_vid():
    info = make_port("/dev/ttyACM0", description="Arduino Mega 2560")
    assert _score_port(info) == 0


def test_score_known_clone_vid():
    info = make_port("/dev/ttyUSB0", vid=0x1A86, description="USB-SERIAL CH340")
    assert _score_port(info) == 1


def test_score_text_hint_without_vid():
    info = make_port("/dev/ttyUSB0", description="USB-SERIAL CH340")
    assert _score_port(info) == 2


def test_score_skips_bluetooth():
    info = make_port(
        "/dev/ttyACM0",
        vid=0x2341,
        description="Arduino Bluetooth",
    )
    assert _score_port(info) is None


def test_score_skips_linux_ttys(monkeypatch):
    monkeypatch.setattr(arduino.sys, "platform", "linux")
    info = make_port("/dev/ttyS0", vid=0x2341, description="Arduino")
    assert _score_port(info) is None


def test_score_skips_unknown_ports():
    info = make_port("/dev/ttyUSB9", description="Unknown gadget")
    assert _score_port(info) is None


def test_score_mac_usbmodem(monkeypatch):
    monkeypatch.setattr(arduino.sys, "platform", "darwin")
    info = make_port("/dev/cu.usbmodem14101")
    assert _score_port(info) == 2


def test_linux_by_id_ports_missing_dir(tmp_path, monkeypatch):
    missing = tmp_path / "serial" / "by-id"
    monkeypatch.setattr(arduino, "Path", lambda _path: missing)
    assert _linux_by_id_ports() == []


def test_linux_by_id_ports_matches_arduino_symlink(tmp_path, monkeypatch):
    by_id = tmp_path / "by-id"
    by_id.mkdir()
    real = tmp_path / "ttyACM0"
    real.touch()
    (by_id / "usb-Arduino__www.arduino.cc__0043_x").symlink_to(real)
    (by_id / "usb-Unrelated_Device_x").symlink_to(real)
    monkeypatch.setattr(arduino, "Path", lambda _path: by_id)

    assert _linux_by_id_ports() == [str(real)]


@patch("arduino._linux_by_id_ports", return_value=["/dev/ttyACM0"])
def test_find_arduino_port_linux_prefers_by_id(_by_id, monkeypatch):
    monkeypatch.setattr(arduino.sys, "platform", "linux")
    assert find_arduino_port() == "/dev/ttyACM0"


@patch("arduino._linux_by_id_ports", return_value=[])
@patch("arduino.list_ports.comports")
def test_find_arduino_port_picks_best_score(mock_comports, _by_id, monkeypatch):
    monkeypatch.setattr(arduino.sys, "platform", "linux")
    clone = make_port("/dev/ttyUSB0", vid=0x1A86, description="CH340")
    official = make_port("/dev/ttyACM0", vid=0x2341, description="Arduino Uno")
    mock_comports.return_value = [clone, official]
    assert find_arduino_port() == "/dev/ttyACM0"


@patch("arduino.list_ports.comports")
def test_find_arduino_port_windows_skips_by_id(mock_comports, monkeypatch):
    monkeypatch.setattr(arduino.sys, "platform", "win32")
    mock_comports.return_value = [
        make_port("COM3", vid=0x2341, description="Arduino Uno"),
    ]
    assert find_arduino_port() == "COM3"


@patch("arduino._linux_by_id_ports", return_value=[])
@patch("arduino.list_ports.comports", return_value=[])
def test_find_arduino_port_none(_comports, _by_id, monkeypatch):
    monkeypatch.setattr(arduino.sys, "platform", "linux")
    assert find_arduino_port() is None


def test_ringlight_starts_disconnected():
    ring = RingLight()
    assert ring.connected is False
    assert ring.port is None
    assert ring.baud == BAUD_RATE


@patch("arduino.time.sleep")
@patch("arduino.find_arduino_port", return_value="/dev/ttyACM0")
def test_connect_opens_detected_port(mock_find, mock_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    ring = RingLight(boot_delay_s=0.01)
    with patch("arduino.serial.Serial", return_value=fake) as mock_serial:
        assert ring.connect() == "/dev/ttyACM0"

    mock_find.assert_called_once()
    mock_serial.assert_called_once_with("/dev/ttyACM0", BAUD_RATE, timeout=1)
    mock_sleep.assert_called_once_with(0.01)
    assert ring.connected
    assert ring.port == "/dev/ttyACM0"


@patch("arduino.time.sleep")
@patch("arduino.find_arduino_port")
def test_connect_uses_explicit_port(mock_find, _sleep):
    fake = FakeSerial("COM5", BAUD_RATE)
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        assert ring.connect("COM5") == "COM5"
    mock_find.assert_not_called()
    assert ring.port == "COM5"


@patch("arduino.find_arduino_port", return_value=None)
def test_connect_raises_when_no_port(_find):
    ring = RingLight()
    with pytest.raises(RuntimeError, match="No Arduino serial port found"):
        ring.connect()
    assert ring.connected is False


@patch("arduino.time.sleep")
def test_connect_drains_boot_banner(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    fake.in_waiting = 0
    fake.banner_lines = [b"aiNeopixels serial server ready\n"]
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
    assert fake.banner_lines == []


@patch("arduino.time.sleep")
def test_connect_ignores_oserror_while_draining(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    fake.in_waiting = 1
    fake.readline_error = OSError("device gone")
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
    assert ring.connected


@patch("arduino.time.sleep")
def test_readline_returns_sketch_reply(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
        fake.banner_lines = [b"OK\r\n"]
        assert ring.readline() == "OK"


@patch("arduino.time.sleep")
def test_readline_skips_boot_banner(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
        fake.banner_lines = [
            b"aiNeopixels serial server ready\r\n",
            b"OK\r\n",
        ]
        assert ring.readline() == "OK"


def test_send_color_and_off_require_connection():
    ring = RingLight()
    with pytest.raises(RuntimeError, match="Arduino is not connected"):
        ring.send_color(1, 2, 3, 4)
    with pytest.raises(RuntimeError, match="Arduino is not connected"):
        ring.send_off()
    with pytest.raises(RuntimeError, match="Arduino is not connected"):
        ring.readline()


@patch("arduino.time.sleep")
def test_send_color_writes_lf_terminated_command(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
        assert ring.send_color(100, 0, 0, 200) == "W100,R0,G0,B200"
    assert fake.written == b"W100,R0,G0,B200\n"


@patch("arduino.time.sleep")
def test_send_off_writes_off(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
        ring.send_off()
    assert fake.written == b"OFF\n"


@patch("arduino.time.sleep")
def test_close_sends_off_then_releases_port(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
        ring.close()
    assert fake.written == b"OFF\n"
    assert fake.closed
    assert ring.connected is False
    assert ring.port is None


@patch("arduino.time.sleep")
def test_close_can_skip_off(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
        ring.close(send_off=False)
    assert fake.written == b""
    assert fake.closed


def test_close_is_safe_when_never_connected():
    RingLight().close()


@patch("arduino.time.sleep")
def test_close_still_releases_port_if_off_fails(_sleep):
    fake = FakeSerial("/dev/ttyACM0", BAUD_RATE)
    fake.write = MagicMock(side_effect=OSError("gone"))
    ring = RingLight(boot_delay_s=0)
    with patch("arduino.serial.Serial", return_value=fake):
        ring.connect("/dev/ttyACM0")
        ring.close()
    assert fake.closed
    assert ring.connected is False
