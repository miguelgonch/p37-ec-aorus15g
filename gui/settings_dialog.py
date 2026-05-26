"""
settings_dialog.py — Settings dialog for the AORUS 15G Fan Control GUI.
"""

from pathlib import Path

try:
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout,
        QLabel, QCheckBox, QPushButton, QFrame,
    )
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
except ImportError:
    from PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout,
        QLabel, QCheckBox, QPushButton, QFrame,
    )
    from PyQt5.QtCore import Qt, QUrl
    from PyQt5.QtGui import QDesktopServices


class SettingsDialog(QDialog):
    """
    Modal settings dialog.

    Usage::

        dlg = SettingsDialog(parent=self, settings=current_settings, log_path=AppLogger.log_path())
        if dlg.exec() == QDialog.Accepted:
            new_settings = dlg.get_settings()
    """

    def __init__(self, parent=None, settings: dict = None, log_path: Path = None):
        super().__init__(parent)
        self._log_path = log_path or Path("/tmp/aorus-fan-control/gui.log")
        self._settings = settings or {}

        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        self.setModal(True)

        self._build_ui()

    # ------------------------------------------------------------------ #
    # Build UI                                                             #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 20, 20, 20)

        # ── Title ───────────────────────────────────────────────────────
        title = QLabel("⚙  Settings")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        root.addWidget(title)

        # ── Separator ───────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #30363D;")
        root.addWidget(sep)

        # ── Debug logging checkbox ───────────────────────────────────────
        self._debug_check = QCheckBox("Enable debug logging")
        self._debug_check.setChecked(self._settings.get("debug_logging", False))
        self._debug_check.setToolTip(
            "When enabled, every EC command and its output is written to the log file."
        )
        root.addWidget(self._debug_check)

        # ── Log file path ───────────────────────────────────────────────
        log_section = QVBoxLayout()
        log_section.setSpacing(4)

        log_title = QLabel("Log file:")
        log_title.setStyleSheet("color: #8B949E; font-size: 11px;")
        log_section.addWidget(log_title)

        path_row = QHBoxLayout()
        path_lbl = QLabel(str(self._log_path))
        path_lbl.setStyleSheet(
            "color: #CFD8DC; font-size: 11px; "
            "background: #161B22; border: 1px solid #30363D; "
            "border-radius: 4px; padding: 4px 8px;"
        )
        path_lbl.setWordWrap(True)
        path_row.addWidget(path_lbl, stretch=1)

        open_btn = QPushButton("Open folder")
        open_btn.setFixedWidth(100)
        open_btn.clicked.connect(self._open_log_folder)
        path_row.addWidget(open_btn)

        log_section.addLayout(path_row)
        root.addLayout(log_section)

        root.addStretch()

        # ── Separator ───────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #30363D;")
        root.addWidget(sep2)

        # ── OK / Cancel ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(90)
        ok_btn.setObjectName("apply_btn")   # reuse accent style from main stylesheet
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_settings(self) -> dict:
        """Return the settings dict as configured by the user."""
        return {
            **self._settings,
            "debug_logging": self._debug_check.isChecked(),
        }

    # ------------------------------------------------------------------ #
    # Slots                                                                #
    # ------------------------------------------------------------------ #

    def _open_log_folder(self):
        folder = self._log_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
