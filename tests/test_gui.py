"""Unit tests for the Flet GUI helpers and window behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import flet as ft
import pytest

import ringLight3
from ringLight3 import APP_NAME, ColorChannel, install_linux_taskbar_name, main


def _column(page: MagicMock) -> ft.Column:
    return page.add.call_args.args[0]


def _buttons(column: ft.Column) -> tuple[ft.Button, ft.Button]:
    for control in column.controls:
        if isinstance(control, ft.Row):
            found = [c for c in control.controls if isinstance(c, ft.Button)]
            if len(found) == 2:
                return found[0], found[1]
    raise AssertionError("On/Off buttons not found")


def _sliders(column: ft.Column) -> list[ft.Slider]:
    sliders = []
    for control in column.controls:
        if isinstance(control, ft.Row):
            sliders.extend(c for c in control.controls if isinstance(c, ft.Slider))
    return sliders


def _status(column: ft.Column) -> ft.Text:
    return column.controls[-1]


def launch(ring, *, run_connect: bool = True) -> tuple[MagicMock, ft.Column]:
    """Build the GUI against a fake RingLight and optional connect() call."""
    page = MagicMock()
    page.run_thread = lambda fn: fn() if run_connect else None
    with (
        patch("ringLight3.atexit.register"),
        patch("ringLight3.RingLight", return_value=ring),
    ):
        main(page)
    return page, _column(page)


def test_color_channel_defaults_to_zero():
    channel = ColorChannel("Red", ft.Colors.RED)
    assert channel.name == "Red"
    assert channel.value == 0
    assert channel.slider.min == 0
    assert channel.slider.max == 255
    assert channel.value_text.value == "0"


def test_color_channel_value_rounds_slider_float():
    channel = ColorChannel("White", ft.Colors.BLUE_GREY_200)
    channel.slider.value = 127.6
    assert channel.value == 128


def test_color_channel_value_treats_none_as_zero():
    channel = ColorChannel("Blue", ft.Colors.BLUE)
    channel.slider.value = None
    assert channel.value == 0


def test_color_channel_on_change_updates_readout():
    channel = ColorChannel("Green", ft.Colors.GREEN)
    channel.value_text.update = MagicMock()
    event = MagicMock()
    event.control.value = 200.4
    channel._on_change(event)
    assert channel.value_text.value == "200"
    channel.value_text.update.assert_called_once()


def test_color_channel_build_row_layout():
    channel = ColorChannel("White", ft.Colors.BLUE_GREY_200)
    row = channel.build_row()
    assert isinstance(row, ft.Row)
    assert row.controls[0].value == "White"
    assert row.controls[1] is channel.slider
    assert row.controls[2] is channel.value_text


def test_install_linux_taskbar_name_skipped_off_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(ringLight3.sys, "platform", "win32")
    monkeypatch.setattr(ringLight3.Path, "home", lambda: tmp_path)
    mock_run = MagicMock()
    monkeypatch.setattr(ringLight3.subprocess, "run", mock_run)

    install_linux_taskbar_name()

    mock_run.assert_not_called()
    apps = tmp_path / ".local/share/applications"
    assert not apps.exists()


def test_install_linux_taskbar_name_writes_desktop_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ringLight3.sys, "platform", "linux")
    monkeypatch.setattr(ringLight3.Path, "home", lambda: tmp_path)
    mock_run = MagicMock()
    monkeypatch.setattr(ringLight3.subprocess, "run", mock_run)

    install_linux_taskbar_name()

    desktop = tmp_path / ".local/share/applications/ringlight-control.desktop"
    text = desktop.read_text(encoding="utf-8")
    script = Path(ringLight3.__file__).resolve()
    assert f"Name={APP_NAME}" in text
    assert "StartupWMClass=Flet" in text
    assert "Terminal=false" in text
    assert str(script) in text
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0][0] == "update-desktop-database"
    assert kwargs["check"] is False


def test_main_sets_window_and_starts_disconnected():
    ring = MagicMock()
    page, column = launch(ring, run_connect=False)
    on_button, off_button = _buttons(column)

    assert page.title == APP_NAME
    assert page.window.width == 480
    assert page.window.height == 430
    assert on_button.disabled is True
    assert off_button.disabled is True
    assert _status(column).value == "Looking for Arduino..."
    ring.connect.assert_not_called()


def test_connect_success_enables_buttons():
    ring = MagicMock()
    ring.connect.return_value = "/dev/ttyACM0"
    page, column = launch(ring)
    on_button, off_button = _buttons(column)

    ring.connect.assert_called_once()
    assert on_button.disabled is False
    assert off_button.disabled is False
    assert _status(column).value == "Connected to /dev/ttyACM0 at 115200 baud"
    page.update.assert_called()


def test_connect_failure_keeps_buttons_disabled():
    ring = MagicMock()
    ring.connect.side_effect = RuntimeError("No Arduino serial port found.")
    _page, column = launch(ring)
    on_button, off_button = _buttons(column)

    assert on_button.disabled is True
    assert off_button.disabled is True
    assert _status(column).value == "Not connected: No Arduino serial port found."


def test_on_sends_slider_values():
    ring = MagicMock()
    ring.connect.return_value = "/dev/ttyACM0"
    ring.send_color.return_value = "W10,R20,G30,B40"
    _page, column = launch(ring)
    on_button, _off = _buttons(column)
    white, red, green, blue = _sliders(column)
    white.value, red.value, green.value, blue.value = 10, 20, 30, 40

    on_button.on_click(MagicMock())

    ring.send_color.assert_called_once_with(10, 20, 30, 40)
    assert _status(column).value == "Sent W10,R20,G30,B40"


def test_on_failure_disables_buttons():
    ring = MagicMock()
    ring.connect.return_value = "/dev/ttyACM0"
    ring.send_color.side_effect = RuntimeError("Arduino is not connected.")
    _page, column = launch(ring)
    on_button, off_button = _buttons(column)

    on_button.on_click(MagicMock())

    assert on_button.disabled is True
    assert off_button.disabled is True
    assert _status(column).value == "Send failed: Arduino is not connected."


def test_off_sends_off_without_changing_sliders():
    ring = MagicMock()
    ring.connect.return_value = "/dev/ttyACM0"
    _page, column = launch(ring)
    _on, off_button = _buttons(column)
    sliders = _sliders(column)
    for slider, value in zip(sliders, (11, 22, 33, 44), strict=True):
        slider.value = value

    off_button.on_click(MagicMock())

    ring.send_off.assert_called_once()
    ring.send_color.assert_not_called()
    assert [slider.value for slider in sliders] == [11, 22, 33, 44]
    assert _status(column).value == "Sent OFF"


def test_off_failure_disables_buttons():
    ring = MagicMock()
    ring.connect.return_value = "/dev/ttyACM0"
    ring.send_off.side_effect = RuntimeError("Arduino is not connected.")
    _page, column = launch(ring)
    _on, off_button = _buttons(column)

    off_button.on_click(MagicMock())

    assert _buttons(column)[0].disabled is True
    assert _status(column).value == "Send failed: Arduino is not connected."


def test_disconnect_closes_ring_and_sends_off():
    ring = MagicMock()
    ring.connect.return_value = "/dev/ttyACM0"
    page, _column = launch(ring)

    page.on_disconnect(MagicMock())

    ring.close.assert_called_with(send_off=True)
