"""
ec_controller.py — Subprocess interface to p37ec-aorus15g and set-fan-mode.sh.

All EC access requires root.  Run the whole GUI with sudo:
    sudo python3 gui/main.py

When running as a PyInstaller bundle the companion binaries are extracted into
sys._MEIPASS (the _internal/ sub-directory of the bundle); otherwise they live
one directory above gui/ as usual.
"""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path


def _get_bin_dir() -> Path:
    """Return the directory that contains p37ec-aorus15g and set-fan-mode.sh.

    Inside a PyInstaller --onedir bundle ``sys._MEIPASS`` is the extraction
    directory where the spec places the bundled binaries.  Outside a bundle
    the binaries live in the repository root (one level above gui/).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)                       # bundle: _internal/
    return Path(__file__).resolve().parent.parent       # repo root


_BIN_DIR = _get_bin_dir()
_EC_BIN  = str(_BIN_DIR / "p37ec-aorus15g")
_SH_BIN  = str(_BIN_DIR / "set-fan-mode.sh")

# Ensure execute permission for both files.  PyInstaller may not preserve the
# execute bit on datas entries, so we fix it here at import time.
for _f in (_EC_BIN, _SH_BIN):
    try:
        _mode = os.stat(_f).st_mode
        if not (_mode & 0o111):
            os.chmod(_f, _mode | 0o111)
    except OSError:
        pass

# Map the mode string printed by p37ec-aorus15g to the shell script mode name
_MODE_LABEL_TO_ARG = {
    "Normal mode":       "normal",
    "Quiet mode":        "quiet",
    "Gaming mode":       "gaming",
    "Fix mode":          "fix",
    "Auto Max mode":     "automax",
    "Deep control mode": "deepcontrol",
}

_NULL_LOGGER = logging.getLogger("aorus_fan.null")
_NULL_LOGGER.addHandler(logging.NullHandler())


class ECError(RuntimeError):
    """Raised when an EC subprocess call fails."""


class ECController:
    """Read and write the Embedded Controller via p37ec-aorus15g."""

    def __init__(self, logger: logging.Logger | None = None):
        self._log = logger or _NULL_LOGGER

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def read_status(self) -> dict:
        """
        Run p37ec-aorus15g with no args and parse its output.

        Returns a dict with keys:
            mode        str   e.g. "Normal mode"
            mode_arg    str   shell-script arg, e.g. "normal"
            fan0_pct    int   Fan0 speed %
            fan1_pct    int   Fan1 speed %
            fan0_rpm    int   Fan0 speed RPM
            fan1_rpm    int   Fan1 speed RPM
            target_pct  int   Target speed % (B0/B1)
            screen      bool  True = enabled
        """
        out = self._run([_EC_BIN])
        return self._parse_status(out)

    def set_mode(self, mode_arg: str, speed_pct: int | None = None) -> None:
        """
        Set a fan mode via set-fan-mode.sh.

        mode_arg : one of normal|quiet|gaming|fix|automax|deepcontrol
        speed_pct: required for fix / automax (30–100)
        """
        cmd = ["bash", _SH_BIN, mode_arg]
        if speed_pct is not None:
            cmd.append(str(speed_pct))
        self._log.info(f"Setting fan mode: {mode_arg}" +
                       (f"  speed={speed_pct}%" if speed_pct is not None else ""))
        self._run(cmd)

    def set_register(self, offset: str, value: str) -> None:
        """
        Write a single register or bit.

        Examples:
            set_register("0x09.3", "0")   # enable screen
        """
        self._log.info(f"Writing register {offset} = {value}")
        self._run([_EC_BIN, offset, value])

    def read_cpu_temp(self) -> int | None:
        """Return CPU *package* temperature in °C, or None on failure.

        Priority order (highest accuracy first):
          1. thermal_zone* whose type contains "x86_pkg"  (e.g. x86_pkg_temp)
          2. coretemp hwmon entry labelled "Package id 0"
          3. ``sensors`` stdout — "Package id" line
          4. ``sensors`` stdout — first "Core N" line as last resort

        Note: acpitz is intentionally excluded — it reports ambient/board
        temperature (≈27 °C) regardless of CPU load and is not useful here.
        """
        # 1. x86_pkg_temp thermal zone — most direct CPU package sensor
        try:
            for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
                if not (zone / "type").exists():
                    continue
                if "x86_pkg" in (zone / "type").read_text().strip().lower():
                    raw = int((zone / "temp").read_text().strip())
                    return raw // 1000
        except Exception:
            pass

        # 2. coretemp hwmon — look for the "Package id 0" input
        try:
            for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
                name_file = hwmon / "name"
                if not name_file.exists():
                    continue
                if name_file.read_text().strip().lower() != "coretemp":
                    continue
                for label_file in sorted(hwmon.glob("temp*_label")):
                    if "package" in label_file.read_text().strip().lower():
                        input_file = Path(str(label_file).replace("_label", "_input"))
                        if input_file.exists():
                            raw = int(input_file.read_text().strip())
                            return raw // 1000
        except Exception:
            pass

        # 3 & 4. sensors fallback — prefer "Package id" over individual cores
        try:
            result = subprocess.run(
                ["sensors"], capture_output=True, text=True, timeout=3
            )
            pkg_temp = core_temp = None
            for line in result.stdout.splitlines():
                m = re.search(r"Package id \d+:\s+\+?([\d.]+)°C", line)
                if m:
                    pkg_temp = int(float(m.group(1)))
                    break
                if core_temp is None:
                    m2 = re.search(r"Core \d+:\s+\+?([\d.]+)°C", line)
                    if m2:
                        core_temp = int(float(m2.group(1)))
            if pkg_temp is not None:
                return pkg_temp
            if core_temp is not None:
                return core_temp
        except Exception:
            pass

        return None

    def read_gpu_temp(self) -> int | None:
        """Return NVIDIA GPU temperature in °C via nvidia-smi, or None on failure."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                line = result.stdout.strip().splitlines()[0]
                return int(line.strip())
        except (FileNotFoundError, ValueError, IndexError,
                subprocess.TimeoutExpired):
            pass
        return None

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _run(self, cmd: list[str]) -> str:
        """Run a command, return stdout, raise ECError on failure."""
        self._log.debug(f"EC cmd: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError as exc:
            msg = f"Binary not found: {cmd[0]}"
            self._log.error(msg)
            raise ECError(msg) from exc
        except subprocess.TimeoutExpired as exc:
            msg = f"Command timed out: {' '.join(cmd)}"
            self._log.error(msg)
            raise ECError(msg) from exc

        if result.stdout:
            self._log.debug(f"stdout: {result.stdout.strip()}")
        if result.stderr:
            self._log.debug(f"stderr: {result.stderr.strip()}")

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "(no output)"
            msg = (
                f"Command failed (exit {result.returncode}): {' '.join(cmd)}\n{detail}"
            )
            self._log.error(msg)
            raise ECError(msg)

        return result.stdout

    @staticmethod
    def _parse_status(text: str) -> dict:
        """Parse the tabular output of p37ec-aorus15g (no-arg invocation)."""
        status = {
            "mode":       "Unknown",
            "mode_arg":   "normal",
            "fan0_pct":   0,
            "fan1_pct":   0,
            "fan0_rpm":   0,
            "fan1_rpm":   0,
            "target_pct": 0,
            "screen":     True,
        }

        for line in text.splitlines():
            # Strip ANSI escapes (just in case)
            line = re.sub(r"\x1b\[[0-9;]*m", "", line)
            stripped = line.strip()

            if "Fan current mode:" in stripped:
                val = stripped.split("Fan current mode:")[-1].strip()
                status["mode"] = val
                status["mode_arg"] = _MODE_LABEL_TO_ARG.get(val, "normal")

            elif re.search(r"Fan0 speed \(%\)\s+\[0xB3\]", stripped):
                m = re.search(r"(\d+)%", stripped)
                if m:
                    status["fan0_pct"] = int(m.group(1))

            elif re.search(r"Fan1 speed \(%\)\s+\[0xB4\]", stripped):
                m = re.search(r"(\d+)%", stripped)
                if m:
                    status["fan1_pct"] = int(m.group(1))

            elif re.search(r"Fan0 speed \(RPM\)\s+\[0xFC\]", stripped):
                m = re.search(r"(\d+)\s+RPM", stripped)
                if m:
                    status["fan0_rpm"] = int(m.group(1))

            elif re.search(r"Fan1 speed \(RPM\)\s+\[0xFE\]", stripped):
                m = re.search(r"(\d+)\s+RPM", stripped)
                if m:
                    status["fan1_rpm"] = int(m.group(1))

            elif re.search(r"Fan0 target speed \(%\)\s+\[0xB0\]", stripped):
                m = re.search(r"(\d+)%", stripped)
                if m:
                    status["target_pct"] = int(m.group(1))

            elif re.search(r"Screen\s+\(0 = Enabled\)\s+\[0x09\.3\]", stripped):
                m = re.search(r":\s*(\d)", stripped)
                if m:
                    # 0 = enabled
                    status["screen"] = m.group(1) == "0"

        return status
