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

import threading

import flet as ft

from arduino import BAUD_RATE, RingLight


class ColorChannel:
    def __init__(self, name: str, color: str):
        self.name = name
        self.value_text = ft.Text(value="0", width=44, size=18)
        self.slider = ft.Slider(
            min=0,
            max=255,
            divisions=255,
            value=0,
            label="{value}",
            active_color=color,
            on_change=self._on_change,
            expand=True,
        )

    @property
    def value(self) -> int:
        return int(round(self.slider.value or 0))

    def _on_change(self, e) -> None:
        self.value_text.value = str(int(round(e.control.value or 0)))
        self.value_text.update()

    def build_row(self) -> ft.Row:
        return ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text(value=self.name, width=72, size=20),
                self.slider,
                self.value_text,
            ],
        )


def main(page: ft.Page) -> None:
    page.title = "RingLight Control"
    page.padding = 20
    page.window.width = 480
    page.window.height = 430
    page.window.min_width = 420
    page.window.min_height = 400

    ring = RingLight()
    connect_lock = threading.Lock()

    white = ColorChannel("White", ft.Colors.BLUE_GREY_200)
    red = ColorChannel("Red", ft.Colors.RED)
    green = ColorChannel("Green", ft.Colors.GREEN)
    blue = ColorChannel("Blue", ft.Colors.BLUE)
    channels = (white, red, green, blue)

    status = ft.Text(value="Looking for Arduino...", size=13)
    on_button = ft.Button(content="On", width=110, height=40, disabled=True)
    off_button = ft.Button(content="Off", width=110, height=40, disabled=True)

    def set_connected(connected: bool) -> None:
        on_button.disabled = not connected
        off_button.disabled = not connected

    def set_status(message: str) -> None:
        status.value = message
        page.update()

    def connect() -> None:
        if not connect_lock.acquire(blocking=False):
            return
        try:
            set_connected(False)
            set_status("Connecting to Arduino...")
            try:
                port = ring.connect()
            except Exception as exc:
                set_status(f"Not connected: {exc}")
                return
            set_connected(True)
            set_status(f"Connected to {port} at {BAUD_RATE} baud")
        finally:
            connect_lock.release()

    def send_on(_e) -> None:
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

    def shutdown() -> None:
        ring.close(send_off=True)
        page.window.prevent_close = False
        page.window.close()

    def on_window_event(e) -> None:
        if e.type == ft.WindowEventType.CLOSE:
            shutdown()

    on_button.on_click = send_on
    off_button.on_click = send_off
    page.window.prevent_close = True
    page.window.on_event = on_window_event

    page.add(
        ft.Column(
            expand=True,
            spacing=12,
            controls=[
                *[channel.build_row() for channel in channels],
                ft.Container(height=8),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=40,
                    controls=[on_button, off_button],
                ),
                ft.Container(expand=True),
                status,
            ],
        )
    )

    page.run_thread(connect)


if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
