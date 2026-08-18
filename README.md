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

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

```bash
python ringLight3.py
```

On Windows, close the Arduino IDE Serial Monitor before launching. The app looks
for official Arduino and common clone USB serial chips (CH340, FTDI, CP210x).

## Windows executable

`flet build windows` must be run on Windows. It cannot be cross-compiled from Linux.

1. Install Python 3.10+ from python.org, and Visual Studio 2022 with the
   **Desktop development with C++** workload (needed by Flutter).
2. In this directory:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
flet doctor
python ringLight3.py
flet build windows
```

The executable is written to `build\windows\x64\runner\Release\RingLight.exe`.

A quicker PyInstaller bundle (larger, no Visual Studio) is:

```powershell
flet pack main.py --name RingLight
```

That writes `dist\RingLight.exe`.
