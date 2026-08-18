# RingLight Control

Flet GUI for the microscope-mounted NeoPixel WRGB ring. It finds a classic
Arduino on the serial port and sends the same commands as the MATLAB
`ringLight_GUI`.

## Requires

- Python 3.10 or later
- Arduino running `ringLight.ino`
  (`/home/justin/jkcode/arduino/ringLight/ringLight.ino`)

Close the Arduino Serial Monitor before launching — only one app may hold
the serial port at a time.

## Serial protocol

115200 baud, LF-terminated lines:

- `W128,R64,G32,B0` set ring color (White, Red, Green, Blue; each 0-255)
- `OFF` turn ring off

The Off button sends `OFF` and leaves the slider values unchanged. Closing
the window also sends `OFF` and releases the port.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
source .venv/bin/activate
python ringLight3.py
```
