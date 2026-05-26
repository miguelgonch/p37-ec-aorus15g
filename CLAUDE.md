# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A C program, Bash wrapper, and PySide6 GUI for reading and controlling the Embedded Controller (EC) on the **Gigabyte AORUS 15G KB** laptop (Intel Core i7-10875H + RTX 3070). It enables Linux-based fan mode control equivalent to the Windows AORUS Control Center, plus screen toggling.

**Warning:** Writing incorrect values to EC registers can damage hardware. Always verify register offsets against the target hardware model before modifying.

## Build

### C binary

```bash
g++ p37ec-aorus15g.c -o p37ec-aorus15g -lm
```

The `-lm` flag is required for `round()` from `<math.h>`. The compiled binary must be named `p37ec-aorus15g` because `set-fan-mode.sh` calls it by that exact name.

**The compiled binary is not tracked by git** (listed in `.gitignore`). It must be compiled from source before use. `packaging/build.sh` does this automatically as its first step.

### GUI (PyInstaller bundle)

```bash
bash packaging/build.sh
```

Compiles the C binary, installs `uv` if needed, creates `.venv/`, installs Python deps (PySide6, matplotlib, numpy, pyinstaller), and produces `dist/aorus-fan-control/` — a self-contained bundle that does not require Python on the target machine.

## Usage

### CLI (requires `sudo`)

```bash
# Read all current EC values and enable EC fan control
sudo ./p37ec-aorus15g

# Write a full 8-bit register value
sudo ./p37ec-aorus15g 0xB0 0xE5

# Write a single bit within a register (offset.bit notation, bit 0 = LSB)
sudo ./p37ec-aorus15g 0x08.6 1

# Set a named fan mode (convenience wrapper)
sudo ./set-fan-mode.sh normal|quiet|gaming|deepcontrol|fix|automax [fan-speed%]
# fan-speed% (30–100) is required for "fix" and "automax" modes
```

### GUI

```bash
# Development (from repo root)
sudo python3 gui/main.py

# From the installed bundle (no terminal needed — pkexec prompts for password)
/opt/aorus-fan-control/aorus-fan-control
```

Install system-wide after building:

```bash
sudo bash packaging/install.sh
```

This copies the bundle to `/opt/aorus-fan-control/`, installs the `.desktop` file to `/usr/share/applications/`, and installs the polkit action so pkexec recognises the binary.

`packaging/install.sh` also supports installing from an extracted release tarball — it detects whether a `bundle/` directory sits alongside the script (tarball layout) and adjusts paths accordingly.

## Release Pipeline

Releases are triggered by pushing a `v*` tag (e.g. `v1.0.0`):

```bash
git tag v1.0.0 && git push origin v1.0.0
```

### `.github/workflows/release.yml`

Runs on `v*` tag push. Uses `ubuntu-22.04` (glibc 2.35) for broad compatibility.

1. Installs `g++`, `libgl1`, `libglib2.0-0` (needed for headless PySide6 build)
2. Runs `bash packaging/build.sh` (compiles C binary + PyInstaller bundle)
3. Packages `dist/aorus-fan-control/` plus install scripts into a tarball:
   `aorus-fan-control-vX.Y.Z-linux-x86_64.tar.gz`
4. Generates a SHA-256 checksum file
5. Creates a GitHub Release (via `softprops/action-gh-release@v2`) with both files as assets

No secrets needed — uses the automatic `GITHUB_TOKEN`. Requires **Settings → Actions → General → Workflow permissions → Read and write permissions** on the repo.

Sets `QT_QPA_PLATFORM=offscreen` so PyInstaller's PySide6 analysis phase works without a display.

### `.github/workflows/ci.yml`

Runs on push to `master`/`main` and all PRs. Two jobs:

- **compile** — `g++ p37ec-aorus15g.c -o p37ec-aorus15g -lm` + sanity-checks the binary loads
- **shellcheck** — lints `set-fan-mode.sh`, `dkms/install.sh`, `packaging/build.sh`, `packaging/install.sh`

Does not run the full PyInstaller build (too slow for every PR).

### Release tarball structure

```
aorus-fan-control/
├── bundle/          ← PyInstaller dist/aorus-fan-control/ contents
│   ├── aorus-fan-control
│   └── _internal/
│       ├── p37ec-aorus15g
│       ├── set-fan-mode.sh
│       └── (PySide6, numpy, matplotlib libs)
├── install.sh
├── aorus-fan-control.desktop
└── com.github.aorus-fan-control.policy
```

## Architecture

### `p37ec-aorus15g.c`

Single-file C program. Entry point is `main()`:

- **No args path**: calls `write8(ec, 0x01, 0xA3)` to activate the EC, then reads and prints all status registers.
- **2-arg path**: parses the `offset[.bit]` argument and calls `write1()` or `write8()` to set the value.

EC I/O helpers operate on a `FILE*` handle to `/dev/ec_io` (provided by the `ec_io` DKMS module):
- `initEc()` — runs `modprobe ec_io` then `fopen`s `/dev/ec_io`
- `read8()` / `read16()` / `read1()` — seek + fread at a byte offset
- `write8()` / `write1()` — seek + fwrite; `write1` does a read-modify-write to preserve other bits

### `dkms/ec_io.c`

Custom kernel module that exposes `/dev/ec_io` as a misc device. It provides seekable byte-level read/write over the 256-byte EC address space using the exported `ec_read()`/`ec_write()` symbols from `<linux/acpi.h>`. This design avoids the `LOCKDOWN_DEBUGFS` and `LOCKDOWN_MODULE_PARAMETERS` lockdown restrictions that block the upstream `ec_sys` debugfs approach when Secure Boot is active. Built and signed via DKMS (`dkms/dkms.conf`, `dkms/Makefile`). The DKMS MOK signing key must be enrolled once via `mokutil`.

### `set-fan-mode.sh`

Bash wrapper that translates a mode name into the correct sequence of `p37ec-aorus15g` bit-write calls. First clears all five mode bits to reset to Normal, then sets the single bit for the requested mode (or sets `0xB0`/`0xB1` target speed registers before setting the bit for Fix/AutoMax). Uses `SCRIPT_DIR` to locate `p37ec-aorus15g` relative to the script itself — can be run from any directory.

### `gui/`

PySide6 desktop application (PyQt5 fallback). Five source files:

| File | Role |
|---|---|
| `main.py` | `QMainWindow` entry point; mode panel, status panel, auto-refresh timer, pkexec self-elevation |
| `ec_controller.py` | Subprocess wrapper for the C binary and shell script; parses EC output; reads CPU/GPU temps |
| `fan_curves.py` | Matplotlib-in-Qt chart widget showing fan speed vs temperature curves with live overlays |
| `app_logger.py` | Rotating file logger + JSON settings persistence (`~/.config/aorus-fan-control/`) |
| `settings_dialog.py` | Modal settings dialog (debug logging toggle) |

**Root elevation:** `main.py` calls `os.execvp("pkexec", ...)` before creating `QApplication` when `euid != 0`, forwarding `DISPLAY`, `XAUTHORITY`, `WAYLAND_DISPLAY`, and `XDG_RUNTIME_DIR` through pkexec's environment strip.

**PyInstaller path resolution:** `ec_controller.py` detects `sys.frozen` / `sys._MEIPASS` and looks for `p37ec-aorus15g` and `set-fan-mode.sh` in `sys._MEIPASS` (the `_internal/` directory of the bundle) rather than the repo root. Execute bits are restored at import time via `os.chmod` since PyInstaller does not always preserve them for `datas` entries.

### `packaging/`

| File | Role |
|---|---|
| `aorus-fan-control.spec` | PyInstaller spec (`console=False`, bundles EC binary + shell script) |
| `build.sh` | Compiles C binary → installs uv → `uv venv .venv` → `uv pip install` → `pyinstaller` |
| `install.sh` | Deploys bundle to `/opt/`, desktop file to `/usr/share/applications/`, polkit action; supports both source-repo and tarball-extraction layouts |
| `aorus-fan-control.desktop` | `Terminal=false`, `Exec=/opt/aorus-fan-control/aorus-fan-control` |
| `com.github.aorus-fan-control.policy` | Polkit action (`auth_admin_keep`) for pkexec authentication dialog |

## Key EC Registers

| Register | Description |
|---|---|
| `0x01` | EC activation trigger (write `0xA3` to enable) |
| `0x08.6` | Quiet mode bit |
| `0x06.4` | Fix mode bit |
| `0x0D.0` | AutoMax mode bit |
| `0x0D.7` | Deep control mode bit |
| `0x0C.4` | Gaming mode bit |
| `0xB0` / `0xB1` | Fan0 / Fan1 target speed (Fix & AutoMax) |
| `0xB3` / `0xB4` | Fan0 / Fan1 current speed (raw; divide by 2.29 for %) |
| `0xFC` / `0xFE` | Fan0 / Fan1 current speed (RPM, 16-bit big-endian) |
| `0x03.5` | Touchpad enabled (1 = enabled) |
| `0x09.3` | Screen enabled (0 = enabled) |

**Fan speed encoding:** 100% = 229 decimal = `0xE5` hex. To convert a percentage: `speed_dec = speed% * 229 / 100`.

## Temperature Readings

CPU and GPU temperatures are read outside the EC (not from EC registers):

**CPU package temp** — `ec_controller.read_cpu_temp()` uses this priority chain:
1. `thermal_zone*` whose `type` contains `x86_pkg` (e.g. `x86_pkg_temp`) — most accurate
2. `coretemp` hwmon entry with a `temp*_label` of `"Package id 0"`
3. `sensors` stdout — "Package id" line, then first "Core N" line as last resort

`acpitz` is intentionally excluded; it reports ambient/board temperature (~27 °C) regardless of CPU load.

**GPU temp** — `ec_controller.read_gpu_temp()` calls:
```
nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits
```
Returns `None` silently if `nvidia-smi` is not found. GPU temp is informational only — it does not influence fan mode selection.

## Kernel module and Secure Boot

The program uses a custom DKMS module (`dkms/ec_io.c`) that creates `/dev/ec_io`. Install with `sudo bash dkms/install.sh`, then auto-load on boot with `echo "ec_io" | sudo tee /etc/modules-load.d/ec_io.conf`.

### Why not `ec_sys`?

When Secure Boot is enabled, the kernel lockdown LSM (`integrity` level) blocks `ec_sys` through two independent restrictions:

1. **`LOCKDOWN_MODULE_PARAMETERS`** (`kernel/params.c`) — `module_param_hw` parameters cannot be set at modprobe time. The upstream `ec_sys` registers `write_support` with `module_param_hw`, so `modprobe ec_sys write_support=1` returns `EPERM`.

2. **`LOCKDOWN_DEBUGFS`** (`fs/debugfs/file.c:debugfs_locked_down()`) — `open()` on any debugfs file returns `EPERM` if the file has non-read permission bits OR is opened with write access. The `ec0/io` file has mode `0600`, so even reading it is blocked.

Both restrictions apply regardless of whether the process runs as root.

### Why `ec_io` works

`dkms/ec_io.c` registers a **misc device** (`/dev/ec_io`, mode `0600`). Misc devices are not subject to `LOCKDOWN_DEBUGFS`. It calls `ec_read()`/`ec_write()` directly — these are exported ACPI symbols declared in `<linux/acpi.h>`, so `internal.h` and `first_ec` are not needed. DKMS auto-signs the module with a managed MOK key; enroll it once with `mokutil` and no further action is needed across kernel updates (DKMS rebuilds and re-signs automatically).
