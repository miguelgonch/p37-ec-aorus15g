#!/usr/bin/env python3
"""
main.py — AORUS 15G Fan Control GUI

Launch with:
    cd /path/to/p37-ec-aorus15g
    sudo python3 gui/main.py
"""

import sys
import os
import numpy as np

# ---------------------------------------------------------------------------
# Qt import shim: try PySide6 first, fall back to PyQt5
# ---------------------------------------------------------------------------
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget,
        QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QRadioButton, QButtonGroup,
        QSpinBox, QProgressBar, QComboBox, QGroupBox,
        QMessageBox, QSizePolicy, QFrame,
    )
    from PySide6.QtCore import Qt, QTimer, Signal
    from PySide6.QtGui import QPalette, QColor, QFont
    _QT_BINDING = "PySide6"
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget,
        QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QRadioButton, QButtonGroup,
        QSpinBox, QProgressBar, QComboBox, QGroupBox,
        QMessageBox, QSizePolicy, QFrame,
    )
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal as Signal
    from PyQt5.QtGui import QPalette, QColor, QFont
    _QT_BINDING = "PyQt5"

from app_logger import AppLogger
from ec_controller import ECController, ECError
from fan_curves import FanCurveWidget, FanStatusWidget, DEFAULT_CUSTOM_CURVE
from settings_dialog import SettingsDialog

# ---------------------------------------------------------------------------
# Colour / style constants
# ---------------------------------------------------------------------------
_DARK_BG    = "#0D1117"
_PANEL_BG   = "#161B22"
_BORDER     = "#30363D"
_TEXT_PRI   = "#E6EDF3"
_TEXT_SEC   = "#8B949E"
_ACCENT     = "#4FC3F7"
_BTN_BG     = "#21262D"
_BTN_HOVER  = "#30363D"
_GREEN      = "#3FB950"
_RED        = "#F85149"

_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {_DARK_BG};
    color: {_TEXT_PRI};
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    background-color: {_PANEL_BG};
    border: 1px solid {_BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding: 6px 10px 10px 10px;
    font-weight: bold;
    color: {_TEXT_PRI};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    top: -1px;
    color: {_ACCENT};
    font-size: 12px;
}}
QPushButton {{
    background-color: {_BTN_BG};
    border: 1px solid {_BORDER};
    border-radius: 5px;
    padding: 5px 14px;
    color: {_TEXT_PRI};
}}
QPushButton:hover {{
    background-color: {_BTN_HOVER};
    border-color: {_ACCENT};
}}
QPushButton:pressed {{
    background-color: {_ACCENT};
    color: #000;
}}
QPushButton#apply_btn {{
    background-color: {_ACCENT};
    color: #000;
    font-weight: bold;
    padding: 7px 20px;
}}
QPushButton#apply_btn:hover {{
    background-color: #81D4FA;
}}
QRadioButton {{
    spacing: 8px;
    color: {_TEXT_PRI};
    padding: 3px 0;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
}}
QProgressBar {{
    background-color: #1C2128;
    border: 1px solid {_BORDER};
    border-radius: 4px;
    text-align: center;
    color: {_TEXT_PRI};
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {_ACCENT};
    border-radius: 3px;
}}
QComboBox {{
    background-color: {_BTN_BG};
    border: 1px solid {_BORDER};
    border-radius: 4px;
    padding: 3px 8px;
    color: {_TEXT_PRI};
}}
QComboBox QAbstractItemView {{
    background-color: {_PANEL_BG};
    border: 1px solid {_BORDER};
    color: {_TEXT_PRI};
    selection-background-color: {_BTN_HOVER};
}}
QSpinBox {{
    background-color: {_BTN_BG};
    border: 1px solid {_BORDER};
    border-radius: 4px;
    padding: 3px 6px;
    color: {_TEXT_PRI};
    max-width: 80px;
}}
QDialog {{
    background-color: {_DARK_BG};
    color: {_TEXT_PRI};
}}
QCheckBox {{
    color: {_TEXT_PRI};
    spacing: 8px;
}}
"""

# Banner level → (border colour, background colour)
_BANNER_STYLES = {
    "error":   ("#F85149", "#2D1B1B"),
    "success": ("#3FB950", "#1B2D1B"),
    "info":    ("#4FC3F7", "#1B252D"),
}

# Fan modes: (display label, shell script arg, needs speed?)
_MODES = [
    ("Normal",       "normal",      False),
    ("Quiet",        "quiet",       False),
    ("Gaming",       "gaming",      False),
    ("Fix",          "fix",         True),
    ("AutoMax",      "automax",     True),
    ("Deep Control", "deepcontrol", False),
    ("Custom",       "custom",      False),   # software-simulated curve
]

# Map shell arg → EC output label (for syncing radio buttons with live data)
_ARG_TO_MODE_LABEL = {
    "normal":      "Normal mode",
    "quiet":       "Quiet mode",
    "gaming":      "Gaming mode",
    "fix":         "Fix mode",
    "automax":     "Auto Max mode",
    "deepcontrol": "Deep control mode",
    "custom":      "Custom mode",   # never reported by EC; used for display only
}

_REFRESH_INTERVALS = [
    ("Off",  0),
    ("1 s",  1000),
    ("2 s",  2000),
    ("5 s",  5000),
    ("10 s", 10000),
]


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self._settings = AppLogger.load_settings()
        AppLogger.configure(self._settings.get("debug_logging", False))
        self._log = AppLogger.get()

        self._ec = ECController(logger=self._log)
        self._last_status: dict = {}
        self._refresh_in_progress = False
        self._banner_timer: QTimer | None = None
        # True when the user has clicked a radio button but not yet applied —
        # prevents auto-refresh from overwriting their pending selection.
        self._user_modified_mode: bool = False

        # Custom mode state
        self._custom_mode_active: bool = False
        self._last_cpu_temp: int | None = None
        self._last_gpu_temp: int | None = None
        # Load custom curve from settings (None → fall back to DEFAULT_CUSTOM_CURVE)
        raw = self._settings.get("custom_curve_points")
        if isinstance(raw, list) and len(raw) >= 2:
            self._custom_curve_points: list[tuple[int, int]] = [
                (int(p[0]), int(p[1])) for p in raw
            ]
        else:
            self._custom_curve_points = list(DEFAULT_CUSTOM_CURVE)
        # Software control loop timer (5-second poll)
        self._custom_loop_timer = QTimer(self)
        self._custom_loop_timer.setInterval(5_000)
        self._custom_loop_timer.timeout.connect(self._custom_loop_tick)

        self.setWindowTitle("🌀 AORUS 15G Fan Control")
        self.setMinimumSize(820, 680)

        self._build_ui()
        self._apply_stylesheet()

        self._log.info(f"GUI started (Qt binding: {_QT_BINDING})")

        # Initial data load (deferred so window paints first)
        QTimer.singleShot(200, self._refresh)

    # ------------------------------------------------------------------ #
    # UI construction                                                       #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Top bar ─────────────────────────────────────────────────────
        root.addLayout(self._build_topbar())

        # ── Error / status banner (initially hidden) ─────────────────────
        self._banner_widget = self._build_banner()
        root.addWidget(self._banner_widget)

        # ── Middle row: mode panel | status panel ───────────────────────
        mid = QHBoxLayout()
        mid.setSpacing(10)
        mid.addWidget(self._build_mode_panel(), stretch=2)
        mid.addWidget(self._build_status_panel(), stretch=3)
        root.addLayout(mid)

        # ── Charts row: edit curve (left) | live status (right) ─────────
        charts_row = QHBoxLayout()
        charts_row.setSpacing(8)

        # Left — "Fan Curve" edit chart (not refreshed by auto-refresh)
        edit_group = QGroupBox("Fan Curve")
        edit_layout = QVBoxLayout(edit_group)
        edit_layout.setContentsMargins(6, 10, 6, 6)
        self._edit_widget = FanCurveWidget(self)
        self._edit_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        edit_layout.addWidget(self._edit_widget)
        charts_row.addWidget(edit_group, stretch=1)

        # Right — "Live Status" chart (updated every refresh tick)
        status_group = QGroupBox("Live Status")
        status_layout = QVBoxLayout(status_group)
        status_layout.setContentsMargins(6, 10, 6, 6)
        self._status_widget = FanStatusWidget(self)
        self._status_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        status_layout.addWidget(self._status_widget)
        charts_row.addWidget(status_group, stretch=1)

        root.addLayout(charts_row, stretch=4)

        # Inject saved custom curve and wire the curve_edited signal
        self._edit_widget.set_custom_points(self._custom_curve_points)
        self._edit_widget.curve_edited.connect(self._on_custom_curve_edited)

    # ── Top bar ─────────────────────────────────────────────────────────

    def _build_topbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        title = QLabel("AORUS 15G Fan Control")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {_ACCENT};")
        bar.addWidget(title)

        bar.addStretch()

        self._mode_badge = QLabel("—")
        self._mode_badge.setObjectName("mode_badge")
        self._mode_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_badge.setFixedHeight(26)
        self._mode_badge.setStyleSheet(
            f"background-color: {_ACCENT}; color: #000; font-weight: bold; "
            f"border-radius: 4px; padding: 2px 10px; font-size: 12px;"
        )
        bar.addWidget(self._mode_badge)

        bar.addSpacing(16)

        # Auto-refresh selector
        refresh_label = QLabel("Auto-refresh:")
        refresh_label.setStyleSheet(f"color: {_TEXT_SEC};")
        bar.addWidget(refresh_label)

        self._refresh_combo = QComboBox()
        for label, _ in _REFRESH_INTERVALS:
            self._refresh_combo.addItem(label)
        self._refresh_combo.setCurrentIndex(2)   # default: 2 s
        self._refresh_combo.currentIndexChanged.connect(self._on_refresh_interval_changed)
        bar.addWidget(self._refresh_combo)

        bar.addSpacing(8)

        # Settings button
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedWidth(36)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self._open_settings)
        bar.addWidget(settings_btn)

        bar.addSpacing(4)

        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setFixedWidth(90)
        refresh_btn.clicked.connect(self._refresh)
        bar.addWidget(refresh_btn)

        # Timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._on_refresh_interval_changed(self._refresh_combo.currentIndex())

        return bar

    # ── Banner ──────────────────────────────────────────────────────────

    def _build_banner(self) -> QWidget:
        """Build the inline status/error banner widget (initially hidden)."""
        container = QWidget()
        container.setVisible(False)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self._banner_label = QLabel("")
        self._banner_label.setWordWrap(True)
        self._banner_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._banner_label, stretch=1)

        dismiss_btn = QPushButton("×")
        dismiss_btn.setFixedSize(24, 24)
        dismiss_btn.setFlat(True)
        dismiss_btn.setStyleSheet(
            f"QPushButton {{ color: {_TEXT_PRI}; font-size: 16px; border: none; "
            f"background: transparent; }}"
            f"QPushButton:hover {{ color: #fff; }}"
        )
        dismiss_btn.clicked.connect(self._hide_banner)
        layout.addWidget(dismiss_btn, alignment=Qt.AlignmentFlag.AlignTop)

        return container

    def _show_banner(
        self,
        msg: str,
        level: str = "error",
        auto_dismiss_ms: int = 0,
    ) -> None:
        """
        Display the inline banner with the given message.

        level          : 'error' | 'success' | 'info'
        auto_dismiss_ms: if > 0, banner hides after this many milliseconds
        """
        border_col, bg_col = _BANNER_STYLES.get(level, _BANNER_STYLES["info"])

        self._banner_widget.setStyleSheet(
            f"QWidget {{ background-color: {bg_col}; border: 1px solid {border_col}; "
            f"border-radius: 5px; }}"
        )
        self._banner_label.setStyleSheet(f"color: {_TEXT_PRI}; font-size: 12px;")
        self._banner_label.setText(msg)
        self._banner_widget.setVisible(True)

        # Cancel any running auto-dismiss
        if self._banner_timer is not None:
            self._banner_timer.stop()
            self._banner_timer = None

        if auto_dismiss_ms > 0:
            self._banner_timer = QTimer(self)
            self._banner_timer.setSingleShot(True)
            self._banner_timer.timeout.connect(self._hide_banner)
            self._banner_timer.start(auto_dismiss_ms)

        # Log at the appropriate level
        log_fn = {
            "error":   self._log.error,
            "success": self._log.info,
            "info":    self._log.info,
        }.get(level, self._log.info)
        log_fn(f"[banner/{level}] {msg}")

    def _hide_banner(self) -> None:
        if self._banner_timer is not None:
            self._banner_timer.stop()
            self._banner_timer = None
        self._banner_widget.setVisible(False)

    # ── Fan mode panel ──────────────────────────────────────────────────

    def _build_mode_panel(self) -> QGroupBox:
        group = QGroupBox("Fan Mode")
        layout = QVBoxLayout(group)
        layout.setSpacing(4)

        self._mode_btn_group = QButtonGroup(self)
        self._mode_radios: dict[str, QRadioButton] = {}    # arg → radio
        self._speed_spins: dict[str, QSpinBox] = {}

        for i, (label, arg, needs_speed) in enumerate(_MODES):
            row = QHBoxLayout()
            radio = QRadioButton(label)
            self._mode_radios[arg] = radio
            self._mode_btn_group.addButton(radio, i)
            radio.toggled.connect(self._on_mode_radio_toggled)
            row.addWidget(radio)

            if needs_speed:
                spin = QSpinBox()
                spin.setRange(30, 100)
                spin.setSuffix(" %")
                spin.setValue(75)
                spin.setVisible(False)
                spin.setObjectName(f"speed_spin_{arg}")
                self._speed_spins[arg] = spin
                row.addWidget(spin)

            row.addStretch()
            layout.addLayout(row)

        layout.addSpacing(8)

        self._apply_btn = QPushButton("Apply Mode")
        self._apply_btn.setObjectName("apply_btn")
        self._apply_btn.clicked.connect(self._apply_mode)
        layout.addWidget(self._apply_btn)

        layout.addStretch()
        return group

    # ── Status panel ────────────────────────────────────────────────────

    def _build_status_panel(self) -> QGroupBox:
        group = QGroupBox("Current Status")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        # Fan bars
        fan_grid = QGridLayout()
        fan_grid.setColumnStretch(1, 1)

        for row, (fan_name, rpm_attr, pct_attr) in enumerate([
            ("Fan 0", "_fan0_rpm_label", "_fan0_bar"),
            ("Fan 1", "_fan1_rpm_label", "_fan1_bar"),
        ]):
            name_lbl = QLabel(fan_name)
            name_lbl.setStyleSheet(f"color: {_TEXT_SEC};")
            fan_grid.addWidget(name_lbl, row, 0)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("%v%")
            bar.setFixedHeight(20)
            setattr(self, pct_attr, bar)
            fan_grid.addWidget(bar, row, 1)

            rpm_lbl = QLabel("— RPM")
            rpm_lbl.setFixedWidth(90)
            rpm_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rpm_lbl.setStyleSheet(f"color: {_TEXT_PRI}; font-size:12px;")
            setattr(self, rpm_attr, rpm_lbl)
            fan_grid.addWidget(rpm_lbl, row, 2)

        layout.addLayout(fan_grid)

        # Target speed
        tgt_row = QHBoxLayout()
        tgt_row.addWidget(QLabel("Target speed:"))
        self._target_label = QLabel("—")
        self._target_label.setStyleSheet(f"color: {_ACCENT}; font-weight: bold;")
        tgt_row.addWidget(self._target_label)
        tgt_row.addStretch()
        layout.addLayout(tgt_row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_BORDER};")
        layout.addWidget(sep)

        # Screen toggle (touchpad removed)
        toggle_row = QHBoxLayout()

        self._screen_btn = QPushButton("🖥 Screen: —")
        self._screen_btn.setCheckable(False)
        self._screen_btn.setFixedHeight(32)
        self._screen_btn.clicked.connect(self._toggle_screen)
        toggle_row.addWidget(self._screen_btn)

        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        # CPU + GPU temp
        temp_row = QHBoxLayout()
        temp_row.addWidget(QLabel("CPU:"))
        self._cpu_temp_label = QLabel("—")
        self._cpu_temp_label.setStyleSheet("color: #A5D6A7;")   # green, matches chart
        temp_row.addWidget(self._cpu_temp_label)

        temp_row.addSpacing(16)

        temp_row.addWidget(QLabel("GPU:"))
        self._gpu_temp_label = QLabel("—")
        self._gpu_temp_label.setStyleSheet("color: #CE93D8;")   # purple, matches chart
        temp_row.addWidget(self._gpu_temp_label)

        temp_row.addStretch()
        layout.addLayout(temp_row)

        layout.addStretch()
        return group

    # ------------------------------------------------------------------ #
    # Slots                                                                #
    # ------------------------------------------------------------------ #

    def _on_mode_radio_toggled(self, checked: bool):
        """Show/hide speed spinboxes based on selected mode.

        Also enables/disables chart interactivity when the Custom radio is
        selected — the user can preview and edit the curve before clicking Apply.
        """
        if not checked:
            return
        # Mark that the user has made a pending selection; suppress radio
        # overwrites from auto-refresh until they Apply or the EC syncs back.
        self._user_modified_mode = True
        for arg, spin in self._speed_spins.items():
            spin.setVisible(self._mode_radios[arg].isChecked())

        # Toggle chart edit mode and preview the selected curve.
        # Guard: _edit_widget is created after _build_mode_panel, so skip if
        # the signal fires during widget construction.
        if not hasattr(self, "_edit_widget"):
            return

        custom_radio = self._mode_radios.get("custom")
        if custom_radio and custom_radio.isChecked():
            # Show Custom curve with amber drag handles
            self._edit_widget.set_interactive(True, self._custom_curve_points)
            self._edit_widget.update_curve("Custom mode")
        else:
            # Disable interactivity unless the custom loop is already running
            if not self._custom_mode_active:
                self._edit_widget.set_interactive(False)
            # Preview the selected mode's curve
            checked_id = self._mode_btn_group.checkedId()
            if 0 <= checked_id < len(_MODES):
                _, arg, _ = _MODES[checked_id]
                mode_label = _ARG_TO_MODE_LABEL.get(arg, "Normal mode")
                target = (self._speed_spins[arg].value()
                          if arg in self._speed_spins else
                          self._last_status.get("target_pct", 75))
                self._edit_widget.update_curve(mode_label, target_pct=target)

    def _on_refresh_interval_changed(self, index: int):
        _, ms = _REFRESH_INTERVALS[index]
        self._timer.stop()
        if ms > 0:
            self._timer.start(ms)

    def _open_settings(self):
        dlg = SettingsDialog(
            parent=self,
            settings=self._settings,
            log_path=AppLogger.log_path(),
        )
        dlg.setStyleSheet(self.styleSheet())
        if dlg.exec():
            new_settings = dlg.get_settings()
            self._settings = new_settings
            AppLogger.save_settings(new_settings)
            AppLogger.configure(new_settings.get("debug_logging", False))
            self._log = AppLogger.get()
            self._ec = ECController(logger=self._log)
            self._log.info("Settings updated")
            self._show_banner("Settings saved.", level="success", auto_dismiss_ms=3000)

    def _refresh(self):
        if self._refresh_in_progress:
            self._log.debug("Refresh skipped — already in progress")
            return
        self._refresh_in_progress = True
        try:
            status = self._ec.read_status()
            cpu_temp = self._ec.read_cpu_temp()
            gpu_temp = self._ec.read_gpu_temp()
            self._log.debug(
                f"Status: mode={status.get('mode')}, "
                f"fan0={status.get('fan0_pct')}%/{status.get('fan0_rpm')}RPM, "
                f"fan1={status.get('fan1_pct')}%/{status.get('fan1_rpm')}RPM, "
                f"cpu={cpu_temp}°C  gpu={gpu_temp}°C"
            )
            self._last_cpu_temp = cpu_temp
            self._last_gpu_temp = gpu_temp
            self._update_widgets(status, cpu_temp, gpu_temp)
            self._last_status = status
        except ECError as exc:
            self._timer.stop()
            self._show_banner(
                f"EC read failed — {exc}\n"
                "Make sure the ec_io module is loaded (sudo modprobe ec_io).",
                level="error",
            )
        finally:
            self._refresh_in_progress = False

    def _apply_mode(self):
        checked_id = self._mode_btn_group.checkedId()
        if checked_id < 0:
            self._show_banner(
                "Please select a fan mode first.",
                level="info",
                auto_dismiss_ms=3000,
            )
            return

        label, arg, needs_speed = _MODES[checked_id]

        # ---- Custom mode: start software control loop ----
        if arg == "custom":
            self._start_custom_mode()
            return

        # ---- Any other mode: stop custom loop first ----
        self._stop_custom_mode()

        speed_pct = None
        if needs_speed and arg in self._speed_spins:
            speed_pct = self._speed_spins[arg].value()

        try:
            self._ec.set_mode(arg, speed_pct)
        except ECError as exc:
            self._show_banner(
                f"Could not apply mode '{label}' — {exc}",
                level="error",
            )
            return

        speed_str = f" @ {speed_pct}%" if speed_pct is not None else ""
        self._show_banner(
            f"Mode set to {label}{speed_str}",
            level="success",
            auto_dismiss_ms=4000,
        )
        # Clear the pending-selection guard so the post-apply refresh is
        # allowed to sync the radio buttons to the newly written EC mode.
        self._user_modified_mode = False
        # Wait 800 ms before refreshing — gives the EC time to settle and
        # avoids racing with the auto-refresh timer
        QTimer.singleShot(800, self._refresh)

    def _toggle_screen(self):
        enabled = self._last_status.get("screen", True)
        # 0x09.3: 0 = enabled, 1 = disabled
        new_val = "1" if enabled else "0"
        try:
            self._ec.set_register("0x09.3", new_val)
        except ECError as exc:
            self._show_banner(
                f"Could not toggle screen — {exc}",
                level="error",
            )
            return
        QTimer.singleShot(200, self._refresh)

    # ------------------------------------------------------------------ #
    # Widget update                                                         #
    # ------------------------------------------------------------------ #

    def _update_widgets(self, status: dict, cpu_temp: int | None, gpu_temp: int | None = None):
        # Mode badge
        ec_mode_label = status.get("mode", "Unknown")
        # When the custom software loop is active, the EC reports "Fix mode"
        # (because that's what we're writing), but we display "Custom mode".
        display_mode = "Custom mode" if self._custom_mode_active else ec_mode_label
        self._mode_badge.setText(display_mode)

        # Only sync the mode selector when the user has no pending selection.
        # This prevents auto-refresh from overwriting a choice the user hasn't
        # applied yet.
        if not self._user_modified_mode:
            if self._custom_mode_active:
                # Keep the Custom radio checked; don't let EC status (Fix mode)
                # override it while the software loop is running.
                for arg, radio in self._mode_radios.items():
                    radio.blockSignals(True)
                    radio.setChecked(arg == "custom")
                    radio.blockSignals(False)
                for arg, spin in self._speed_spins.items():
                    spin.setVisible(False)
            else:
                mode_arg = status.get("mode_arg", "normal")
                for arg, radio in self._mode_radios.items():
                    radio.blockSignals(True)
                    radio.setChecked(arg == mode_arg)
                    radio.blockSignals(False)
                # Show/hide speed spinboxes
                for arg, spin in self._speed_spins.items():
                    spin.setVisible(self._mode_radios[arg].isChecked())
                # Pre-fill spinbox with current target
                target_pct = status.get("target_pct", 75)
                for arg, spin in self._speed_spins.items():
                    if self._mode_radios[arg].isChecked():
                        spin.blockSignals(True)
                        spin.setValue(target_pct)
                        spin.blockSignals(False)

        # Fan bars
        fan0_pct = status.get("fan0_pct", 0)
        fan1_pct = status.get("fan1_pct", 0)
        self._fan0_bar.setValue(fan0_pct)
        self._fan1_bar.setValue(fan1_pct)
        self._fan0_rpm_label.setText(f"{status.get('fan0_rpm', 0):,} RPM")
        self._fan1_rpm_label.setText(f"{status.get('fan1_rpm', 0):,} RPM")

        # Target speed
        target_pct = status.get("target_pct", 75)
        self._target_label.setText(f"{target_pct} %")

        # CPU + GPU temp
        self._cpu_temp_label.setText(f"{cpu_temp} °C" if cpu_temp is not None else "n/a")
        self._gpu_temp_label.setText(f"{gpu_temp} °C" if gpu_temp is not None else "n/a")

        # Screen toggle button
        scr = status.get("screen", True)
        scr_text = "ON ✓" if scr else "OFF ✗"
        scr_color = _GREEN if scr else _RED
        self._screen_btn.setText(f"🖥 Screen: {scr_text}")
        self._screen_btn.setStyleSheet(
            f"QPushButton {{ border: 1px solid {scr_color}; color: {scr_color}; }}"
        )

        # ---- Edit chart (left) ----------------------------------------
        # Only sync to EC mode when the user has no pending selection.
        # If the user has selected a radio or is dragging, leave it alone.
        if not self._user_modified_mode and not self._edit_widget.is_dragging():
            self._edit_widget.update_curve(display_mode, target_pct=target_pct)

        # ---- Status chart (right) — always updated with live data ------
        curve_pts = self._custom_curve_points if self._custom_mode_active else None
        self._status_widget.update_status(
            mode=display_mode,
            fan0_pct=fan0_pct,
            fan1_pct=fan1_pct,
            target_pct=target_pct,
            cpu_temp=cpu_temp,
            gpu_temp=gpu_temp,
            curve_pts=curve_pts,
        )

    # ------------------------------------------------------------------ #
    # Custom mode control loop                                             #
    # ------------------------------------------------------------------ #

    def _start_custom_mode(self) -> None:
        """Activate the software-simulated custom fan curve control loop."""
        self._custom_mode_active = True
        self._edit_widget.set_interactive(True, self._custom_curve_points)
        self._edit_widget.update_curve("Custom mode")
        self._custom_loop_timer.start()
        # Immediate first tick — don't wait 5 s for fans to respond
        self._custom_loop_tick()
        self._user_modified_mode = False
        self._show_banner(
            "Custom mode active — drag the left chart's points to adjust the curve.",
            level="info",
            auto_dismiss_ms=6000,
        )
        QTimer.singleShot(800, self._refresh)

    def _stop_custom_mode(self) -> None:
        """Deactivate the custom fan curve control loop."""
        if not self._custom_mode_active:
            return
        self._custom_mode_active = False
        self._custom_loop_timer.stop()
        self._edit_widget.set_interactive(False)
        self._log.info("Custom mode stopped")

    def _custom_loop_tick(self) -> None:
        """
        Software control loop body — called every 5 s while Custom mode is active.

        Reads the current CPU temperature, interpolates the target fan speed from
        the user's custom curve, and writes Fix mode to the EC at that speed.
        The EC then enforces that exact speed in hardware between ticks.
        """
        if not self._custom_mode_active:
            return

        cpu_temp = self._ec.read_cpu_temp()
        if cpu_temp is None:
            self._log.warning("Custom loop: CPU temp unavailable — skipping tick")
            return

        pts = self._custom_curve_points
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        # np.interp clamps to boundary values when cpu_temp is outside [min_x, max_x]
        raw_speed = float(np.interp(cpu_temp, xs, ys))

        # Fix mode minimum is 30 % (set-fan-mode.sh rejects < 30)
        speed_pct = max(30, min(100, round(raw_speed)))

        self._log.info(f"Custom loop: CPU={cpu_temp}°C → Fix {speed_pct}%")
        try:
            self._ec.set_mode("fix", speed_pct)
        except ECError as exc:
            self._log.error(f"Custom loop: EC write failed — {exc}")
            # Do not stop the loop — transient failure; try again next tick

    def _on_custom_curve_edited(self, points: list) -> None:
        """Slot: called when the user finishes dragging a chart breakpoint."""
        self._custom_curve_points = [(int(p[0]), int(p[1])) for p in points]
        # Persist immediately so a crash doesn't lose edits
        self._settings["custom_curve_points"] = [[t, s] for t, s in self._custom_curve_points]
        AppLogger.save_settings(self._settings)
        self._log.info(f"Custom curve updated and saved: {self._custom_curve_points}")
        # If the loop is running, apply the new interpolated speed right away
        if self._custom_mode_active:
            self._custom_loop_tick()

    # ------------------------------------------------------------------ #
    # Window lifecycle                                                      #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:
        """Restore Normal mode on close so fans aren't stuck at a Fix speed."""
        if self._custom_mode_active:
            self._stop_custom_mode()
            try:
                self._ec.set_mode("normal")
                self._log.info("Custom mode: restored Normal mode on close")
            except ECError:
                pass
        event.accept()

    # ------------------------------------------------------------------ #
    # Styling                                                               #
    # ------------------------------------------------------------------ #

    def _apply_stylesheet(self):
        self.setStyleSheet(_STYLESHEET)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _ensure_root() -> None:
    """Re-launch via pkexec when not already running as root.

    This gives a graphical password dialog instead of requiring the user to
    open a terminal and type ``sudo``.  The current process is *replaced*
    (os.execvp) so no zombie is left behind.

    Display-server environment variables are forwarded explicitly because
    pkexec strips the environment before exec-ing the target binary.

    If pkexec is not found on PATH the function returns normally and the
    caller falls through to a plain error dialog.
    """
    if os.geteuid() == 0:
        return

    # Collect display-server env vars to pass through pkexec
    env_args: list[str] = []
    for var in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"):
        val = os.environ.get(var, "")
        if val:
            env_args.append(f"{var}={val}")

    if getattr(sys, "frozen", False):
        # PyInstaller bundle: sys.executable IS the bundle ELF
        target = [sys.executable] + sys.argv[1:]
    else:
        # Plain Python interpreter: pass the script path as well
        target = [sys.executable] + sys.argv

    try:
        os.execvp("pkexec", ["pkexec", "env"] + env_args + target)
        # execvp replaces this process; nothing below runs on success
    except FileNotFoundError:
        # pkexec not available — fall through to the error dialog below
        pass


def main():
    # Attempt graphical root elevation via pkexec before creating QApplication.
    # If the process is already root (e.g. via sudo in a terminal) this is a
    # no-op.  If pkexec is unavailable we fall through and show an error dialog.
    _ensure_root()

    # Still not root (pkexec unavailable or user cancelled)
    if os.geteuid() != 0:
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "Root Required",
            "This application requires root access to read/write the Embedded\n"
            "Controller and pkexec was not found on your system.\n\n"
            "Either install policykit-1 / polkit, or run manually with:\n\n"
            "    sudo python3 gui/main.py"
        )
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("AORUS 15G Fan Control")

    # Apply dark palette as a base so dialogs also look dark
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(_DARK_BG))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(_TEXT_PRI))
    palette.setColor(QPalette.ColorRole.Base,            QColor(_PANEL_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(_BTN_BG))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(_PANEL_BG))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(_TEXT_PRI))
    palette.setColor(QPalette.ColorRole.Text,            QColor(_TEXT_PRI))
    palette.setColor(QPalette.ColorRole.Button,          QColor(_BTN_BG))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(_TEXT_PRI))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(_ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
    app.setPalette(palette)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
