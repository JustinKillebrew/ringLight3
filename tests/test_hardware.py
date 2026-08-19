"""Live serial tests against a classic Arduino running ringLight.ino.

These open the real USB port and skip when no board is found, so the unit
suite still passes on machines without hardware. Close the Arduino Serial
Monitor first — only one program can hold the port.

Run only these tests with:

    pytest -m hardware
    RINGLIGHT_PORT=/dev/ttyACM0 pytest -m hardware
"""

from __future__ import annotations

import os

import pytest

from arduino import RingLight, find_arduino_port

# Dim values so a microscope-mounted ring does not flash at full brightness.
DIM = 12


def _require_port() -> str:
    port = os.environ.get("RINGLIGHT_PORT") or find_arduino_port()
    if not port:
        pytest.skip(
            "No Arduino serial port found. Plug in the board, close the "
            "Serial Monitor, or set RINGLIGHT_PORT."
        )
    return port


@pytest.fixture(scope="module")
def hardware_ring():
    port = _require_port()
    ring = RingLight()
    ring.connect(port)
    yield ring
    ring.close(send_off=True)


@pytest.fixture
def ring(hardware_ring):
    """Same live connection, with leftover sketch replies discarded first."""
    ser = hardware_ring._ser
    if ser is not None:
        old_timeout = ser.timeout
        ser.timeout = 0.05
        try:
            while ser.readline():
                pass
        except OSError:
            pass
        finally:
            ser.timeout = old_timeout
    return hardware_ring


@pytest.mark.hardware
def test_finds_arduino_port():
    port = _require_port()
    assert "ttyACM" in port or "ttyUSB" in port or "COM" in port.upper()


@pytest.mark.hardware
def test_send_color_gets_ok(ring: RingLight):
    cmd = ring.send_color(0, DIM, 0, 0)
    assert cmd == f"W0,R{DIM},G0,B0"
    assert ring.readline() == "OK"


@pytest.mark.hardware
def test_send_off_gets_ok_off(ring: RingLight):
    ring.send_color(0, 0, DIM, 0)
    assert ring.readline() == "OK"
    ring.send_off()
    assert ring.readline() == "OK OFF"


@pytest.mark.hardware
def test_invalid_command_gets_err(ring: RingLight):
    ring._write("HELLO")
    assert ring.readline() == "ERR"
