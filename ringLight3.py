"""Flet GUI to control the microscope-mounted NeoPixel WRGB ring.

Requires:
    - Python 3.10 or later, with flet and pyserial installed
    - Arduino running ringLight.ino
      (/home/justin/jkcode/arduino/ringLight/ringLight.ino)

Usage:
    python ringLight3.py

Close the Arduino Serial Monitor before launching — only one app may
hold the serial port at a time.

Serial protocol (115200 baud, LF-terminated lines sent to Arduino):
    W128,R64,G32,B0   set ring color (White, Red, Green, Blue; each 0-255)
    OFF               turn ring off
"""

from __future__ import annotations

import atexit
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import flet as ft

from arduino import BAUD_RATE, RingLight

# Shown in the window title. On Linux the GNOME dock ignores this and uses
# Flet's hardcoded WM_CLASS ("Flet") unless a matching .desktop file exists.
APP_NAME = "RingLight Control"


def install_linux_taskbar_name() -> None:
    """Tell GNOME to label this window RingLight Control instead of Flet.

    Flet's Linux client is a GTK app whose class is hardcoded to Flet, so
    page.title never reaches the dock. A user .desktop file with
    StartupWMClass=Flet is how the shell maps that window to a real name.
    """
    if sys.platform != "linux":
        return

    apps_dir = Path.home() / ".local/share/applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    exec_line = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    desktop_path = apps_dir / "ringlight-control.desktop"
    desktop_path.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                f"Name={APP_NAME}",
                "Comment=Control a WRGB NeoPixel ring over serial",
                f"Exec={exec_line}",
                "Terminal=false",
                "Categories=Utility;",
                "StartupWMClass=Flet",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # GNOME reads this when the window appears; the updater is optional.
    subprocess.run(
        ["update-desktop-database", str(apps_dir)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class ColorChannel:
    """One labeled slider plus its numeric readout (White, Red, Green, or Blue).

    Flet widgets are objects you keep a handle to, similar to MATLAB uislider
    and uilabel. The slider's on_change callback updates the text next to it.
    """

    def __init__(self, name: str, color: str):
        self.name = name
        self.value_text = ft.Text(value="0", width=44, size=18)
        self.slider = ft.Slider(
            min=0,
            max=255,
            divisions=255,  # 255 steps between 0 and 255 -> integer values
            value=0,
            label="{value}",  # balloon that appears while dragging
            active_color=color,
            on_change=self._on_change,
            expand=True,  # stretch to fill leftover row width
        )

    @property
    def value(self) -> int:
        """Current slider position as an int 0–255.

        `self.slider.value or 0` treats None as 0. round() then int() because
        the slider stores a float even when divisions make it look discrete.
        """
        return int(round(self.slider.value or 0))

    def _on_change(self, e) -> None:
        # e.control is the slider that moved. .update() redraws just that text.
        self.value_text.value = str(int(round(e.control.value or 0)))
        self.value_text.update()

    def build_row(self) -> ft.Row:
        """Name | ====slider==== | 123  laid out left to right."""
        return ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text(value=self.name, width=72, size=20),
                self.slider,
                self.value_text,
            ],
        )


def main(page: ft.Page) -> None:
    """Flet calls this once with a Page — the window we fill with controls.

    Nested functions below (connect, send_on, ...) are closures: they can see
    `page`, `ring`, and the sliders defined in this same function, like MATLAB
    nested functions inside ringLight_GUI.
    """
    page.title = APP_NAME
    page.padding = 20
    page.window.width = 480
    page.window.height = 430
    page.window.min_width = 420
    page.window.min_height = 400

    ring = RingLight()
    # connect() sleeps ~2.5 s waiting for the Arduino reboot. A lock keeps a
    # second connect from starting if the first is still running.
    connect_lock = threading.Lock()

    white = ColorChannel("White", ft.Colors.BLUE_GREY_200)
    red = ColorChannel("Red", ft.Colors.RED)
    green = ColorChannel("Green", ft.Colors.GREEN)
    blue = ColorChannel("Blue", ft.Colors.BLUE)
    channels = (white, red, green, blue)

    status = ft.Text(value="Looking for Arduino...", size=13)
    # Start disabled until connect() succeeds, so On/Off cannot fire too early.
    on_button = ft.Button(content="On", width=110, height=40, disabled=True)
    off_button = ft.Button(content="Off", width=110, height=40, disabled=True)

    def set_connected(connected: bool) -> None:
        on_button.disabled = not connected
        off_button.disabled = not connected

    def set_status(message: str) -> None:
        status.value = message
        page.update()  # push widget changes to the window

    def connect() -> None:
        # blocking=False: if the lock is already taken, skip instead of waiting.
        if not connect_lock.acquire(blocking=False):
            return
        try:
            set_connected(False)
            set_status("Connecting to Arduino...")
            try:
                port = ring.connect()
            except Exception as exc:
                # f"...{exc}" inserts the error text, like MATLAB sprintf.
                set_status(f"Not connected: {exc}")
                return
            set_connected(True)
            set_status(f"Connected to {port} at {BAUD_RATE} baud")
        finally:
            # finally always runs, even after return or an exception.
            connect_lock.release()

    def send_on(_e) -> None:
        # The leading _ on _e means "Flet passes an event we do not use."
        try:
            cmd = ring.send_color(white.value, red.value, green.value, blue.value)
        except Exception as exc:
            set_connected(False)
            set_status(f"Send failed: {exc}")
            return
        set_status(f"Sent {cmd}")

    def send_off(_e) -> None:
        try:
            ring.send_off()
        except Exception as exc:
            set_connected(False)
            set_status(f"Send failed: {exc}")
            return
        set_status("Sent OFF")

    def cleanup(_e=None) -> None:
        # Default _e=None so atexit (no arguments) and Flet (one event) both work.
        ring.close(send_off=True)

    on_button.on_click = send_on
    off_button.on_click = send_off
    # on_disconnect: Flet session ending. atexit: Python process exiting.
    page.on_disconnect = cleanup
    atexit.register(cleanup)

    page.add(
        ft.Column(
            expand=True,
            spacing=12,
            controls=[
                # * unpacks the list of rows into separate Column children.
                *[channel.build_row() for channel in channels],
                ft.Container(height=8),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=40,
                    controls=[on_button, off_button],
                ),
                ft.Container(expand=True),  # flexible spacer above the status line
                status,
            ],
        )
    )

    # Run connect() on a worker thread so the 2.5 s boot wait does not freeze the UI.
    page.run_thread(connect)


if __name__ == "__main__":
    install_linux_taskbar_name()
    # Newer Flet uses ft.run(); older builds used ft.app(target=...).
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
