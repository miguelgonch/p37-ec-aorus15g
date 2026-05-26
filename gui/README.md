# AORUS 15G Fan Control — GUI

A desktop GUI for reading and controlling the Embedded Controller (EC) fan modes on the **Gigabyte AORUS 15G KB** laptop.

## Features

- **Live fan status** — Fan0 / Fan1 speed (% and RPM) with progress bars
- **Mode selector** — Normal, Quiet, Gaming, Fix, AutoMax, Deep Control
- **Speed spinbox** — for Fix and AutoMax modes (30–100 %)
- **Interactive fan-curve chart** — piecewise-linear curves per mode, with live current-speed and CPU-temperature overlays (matplotlib)
- **Touchpad & Screen toggles** — one-click enable/disable
- **Auto-refresh** — configurable polling interval (off / 1 s / 2 s / 5 s / 10 s)

## Requirements

### Ubuntu / Debian (recommended — no pip needed)

```bash
# Option A: PySide6
sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtcore \
                 python3-pyside6.qtgui python3-matplotlib

# Option B: PyQt5 (single package, simpler)
sudo apt install python3-pyqt5 python3-matplotlib
```

### Via pip

```bash
pip install PySide6 matplotlib
# or:
pip install PyQt5 matplotlib
```

> **Note:** `PyQt5` can be substituted for `PySide6` — the code tries PySide6 first and falls back automatically.

## Launch

```bash
# From the repository root — must run as root for EC access
cd /path/to/p37-ec-aorus15g
sudo python gui/main.py
```

## How it works

The GUI calls the existing CLI binaries in the parent directory:

| Action | Command |
|---|---|
| Read status | `./p37ec-aorus15g` (no args) |
| Set fan mode | `./set-fan-mode.sh <mode> [speed%]` |
| Toggle touchpad / screen | `./p37ec-aorus15g <offset.bit> <0\|1>` |

CPU temperature is read from `/sys/class/thermal/thermal_zone*/temp` (falls back to the `sensors` command).

## File layout

```
gui/
├── main.py           # QApplication + MainWindow
├── ec_controller.py  # Subprocess wrapper + output parser
├── fan_curves.py     # Curve data + matplotlib chart widget
└── requirements.txt
```
