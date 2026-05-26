"""
app_logger.py — Rotating file logger + settings persistence for the GUI.

Log location : ~/.local/share/aorus-fan-control/gui.log
Settings file: ~/.config/aorus-fan-control/settings.json
"""

import json
import logging
import logging.handlers
from pathlib import Path

# ---------------------------------------------------------------------------
# Directories / files
# ---------------------------------------------------------------------------
_LOG_DIR     = Path.home() / ".local" / "share" / "aorus-fan-control"
_CONFIG_DIR  = Path.home() / ".config" / "aorus-fan-control"
_LOG_FILE    = _LOG_DIR / "gui.log"
_CONFIG_FILE = _CONFIG_DIR / "settings.json"

_LOGGER_NAME = "aorus_fan"

# Default settings
_DEFAULT_SETTINGS: dict = {
    "debug_logging": False,
    # None → main.py falls back to DEFAULT_CUSTOM_CURVE from fan_curves.py
    "custom_curve_points": None,
}


class AppLogger:
    """
    Singleton-style class that owns the application logger and settings.

    Usage::

        AppLogger.configure(AppLogger.load_settings().get("debug_logging", False))
        log = AppLogger.get()
        log.info("Started")
    """

    _logger: logging.Logger | None = None

    # ------------------------------------------------------------------ #
    # Settings                                                             #
    # ------------------------------------------------------------------ #

    @classmethod
    def load_settings(cls) -> dict:
        """Load settings from JSON; return defaults on any failure."""
        try:
            if _CONFIG_FILE.exists():
                with _CONFIG_FILE.open() as f:
                    data = json.load(f)
                # Merge with defaults so new keys always present
                return {**_DEFAULT_SETTINGS, **data}
        except Exception:
            pass
        return dict(_DEFAULT_SETTINGS)

    @classmethod
    def save_settings(cls, settings: dict) -> None:
        """Persist settings dict to JSON, creating the directory if needed."""
        try:
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with _CONFIG_FILE.open("w") as f:
                json.dump(settings, f, indent=2)
        except Exception as exc:
            cls.get().warning(f"Could not save settings: {exc}")

    # ------------------------------------------------------------------ #
    # Logger                                                               #
    # ------------------------------------------------------------------ #

    @classmethod
    def configure(cls, debug: bool) -> None:
        """
        Set up (or reconfigure) the rotating-file logger.

        debug=True  → level DEBUG   (all EC commands, status reads, etc.)
        debug=False → level INFO    (mode changes, errors only)
        """
        _LOG_DIR.mkdir(parents=True, exist_ok=True)

        logger = logging.getLogger(_LOGGER_NAME)
        logger.setLevel(logging.DEBUG)   # capture everything; handlers filter

        level = logging.DEBUG if debug else logging.INFO

        # ── File handler (rotating, 1 MB, 3 backups) ────────────────────
        file_handler = logging.handlers.RotatingFileHandler(
            _LOG_FILE,
            maxBytes=1_048_576,   # 1 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-7s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

        # ── Stderr handler (always INFO+) ────────────────────────────────
        stderr_handler = logging.StreamHandler()
        stderr_handler.setLevel(logging.INFO)
        stderr_handler.setFormatter(logging.Formatter(
            "%(levelname)-7s  %(message)s"
        ))

        # Replace existing handlers so reconfigure() is idempotent
        logger.handlers.clear()
        logger.addHandler(file_handler)
        logger.addHandler(stderr_handler)

        cls._logger = logger
        logger.info(
            f"Logger configured — level={'DEBUG' if debug else 'INFO'}, "
            f"file={_LOG_FILE}"
        )

    @classmethod
    def get(cls) -> logging.Logger:
        """Return the application logger, auto-configuring at INFO if needed."""
        if cls._logger is None:
            cls.configure(debug=False)
        return cls._logger  # type: ignore[return-value]

    @classmethod
    def log_path(cls) -> Path:
        """Return the path to the active log file."""
        return _LOG_FILE

    @classmethod
    def log_dir(cls) -> Path:
        """Return the log directory."""
        return _LOG_DIR
