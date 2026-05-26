"""
fan_curves.py — Fan-curve data and the two matplotlib-in-Qt chart widgets.

Two widgets are provided:

FanCurveWidget  — "Fan Curve" (left panel)
    Shows the curve shape for the selected / applied fan mode.
    In Custom mode the breakpoints are draggable (amber handles).
    NOT updated on every status refresh — only when the mode selection
    changes or the user edits the curve.

FanStatusWidget — "Live Status" (right panel)
    Shows current fan speeds and CPU/GPU temperatures overlaid on a dim
    copy of the active mode's curve.  Updated on every refresh tick.
    Read-only, no interactivity.

Curve data is approximate, derived from the PNG images in the repo root
(curve_normal.png, curve_quiet.png, curve_gaming.png, curve_deep_control.png).
Each entry is a list of (temp_°C, fan_speed_%) breakpoints for a piecewise-
linear interpolation.
"""

import numpy as np
import matplotlib

# QtAgg (unified backend) works with PySide6, PyQt5, PyQt6, PySide2.
# Older matplotlib (<3.5) only has Qt5Agg — fall back gracefully.
try:
    matplotlib.use("QtAgg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
except (ImportError, ValueError):
    matplotlib.use("Qt5Agg")
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg  # type: ignore

from matplotlib.figure import Figure

# Qt Signal — must be imported *after* the backend is set above.
try:
    from PySide6.QtCore import Signal
    from PySide6.QtCore import Qt
except ImportError:
    from PyQt5.QtCore import pyqtSignal as Signal  # type: ignore
    from PyQt5.QtCore import Qt                    # type: ignore

# ---------------------------------------------------------------------------
# Curve breakpoints:  (temperature °C, fan speed %)
# ---------------------------------------------------------------------------
CURVES: dict[str, list[tuple[int, int]]] = {
    "Normal mode": [
        (0,   0),
        (40,  0),
        (50, 30),
        (65, 45),
        (75, 60),
        (85, 80),
        (95, 100),
    ],
    "Quiet mode": [
        (0,   0),
        (55,  0),
        (65, 20),
        (75, 35),
        (85, 50),
        (95, 60),
        (100, 70),
    ],
    "Gaming mode": [
        (0,  30),
        (45, 40),
        (55, 55),
        (65, 70),
        (75, 85),
        (85, 95),
        (95, 100),
    ],
    "Deep control mode": [
        (0,   0),
        (40, 25),
        (55, 45),
        (65, 60),
        (75, 75),
        (85, 90),
        (95, 100),
    ],
}

# Default custom curve — mirrors Normal mode shape as a safe starting point.
# Exported so main.py can use it as the settings fallback.
DEFAULT_CUSTOM_CURVE: list[tuple[int, int]] = [
    (0,   0),
    (40,  0),
    (50, 30),
    (65, 45),
    (75, 60),
    (85, 80),
    (95, 100),
]

# Modes that use a fixed target speed (no temperature-response curve)
FIXED_SPEED_MODES = {"Fix mode", "Auto Max mode"}

# ---------------------------------------------------------------------------
# Color palette (shared by both widgets)
# ---------------------------------------------------------------------------
_C_CURVE    = "#4FC3F7"   # light blue — preset mode curve
_C_CUSTOM   = "#FFD54F"   # amber — custom mode curve
_C_HANDLE   = "#FFAB40"   # orange-amber — draggable control point handles
_C_CURRENT  = "#FF7043"   # orange — current fan speed line
_C_FAN1     = "#FFAB76"   # lighter orange — fan1 line (distinct from fan0)
_C_CPU_TEMP = "#A5D6A7"   # green — CPU temperature line
_C_GPU_TEMP = "#CE93D8"   # purple — GPU temperature line
_C_POINT    = "#4FC3F7"   # cyan — operating-point dot on status chart
_C_FILL     = "#1E2A3A"   # chart background
_C_AXBG     = "#121C27"   # figure background
_C_GRID     = "#2A3A4A"
_C_TEXT     = "#CFD8DC"

# Hit radius for drag pick (display pixels)
_HIT_RADIUS_PX = 10


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _validate_curve(pts: list) -> bool:
    """Return True when pts is a valid monotone-increasing temp curve."""
    if len(pts) < 2:
        return False
    temps  = [p[0] for p in pts]
    speeds = [p[1] for p in pts]
    return (
        all(t2 > t1 for t1, t2 in zip(temps, temps[1:]))
        and all(0 <= s <= 100 for s in speeds)
        and all(0 <= t <= 105 for t in temps)
    )


def _configure_axes(ax, *, xlabel: bool = True) -> None:
    """Apply the shared dark-theme axis style."""
    ax.set_facecolor(_C_FILL)
    ax.set_xlim(0, 105)
    ax.set_ylim(0, 105)
    if xlabel:
        ax.set_xlabel("Temperature (°C)", color=_C_TEXT, fontsize=9)
    ax.set_ylabel("Fan Speed (%)", color=_C_TEXT, fontsize=9)
    ax.tick_params(colors=_C_TEXT, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(_C_GRID)
    ax.set_xticks(range(0, 106, 10))
    ax.set_yticks(range(0, 106, 10))
    ax.grid(True, which="major", color=_C_GRID,
            linestyle="--", linewidth=0.8, alpha=0.85)
    ax.minorticks_on()
    ax.grid(True, which="minor", color=_C_GRID,
            linestyle=":", linewidth=0.35, alpha=0.4)


# ---------------------------------------------------------------------------
# FanCurveWidget — edit / apply chart (left panel)
# ---------------------------------------------------------------------------

class FanCurveWidget(FigureCanvasQTAgg):
    """
    Displays the fan-speed curve for the currently *selected* mode.

    This chart is the "intent" view — it shows what you are about to apply.
    It is **never** updated by the auto-refresh timer.  It is updated:
      • when the user clicks a mode radio button (preview)
      • when "Apply Mode" is clicked
      • live during drag (Custom mode only)

    In Custom mode the breakpoints become draggable amber handles.
    A ``curve_edited`` signal is emitted on mouse-release with the updated
    list of [temp, speed] pairs.
    """

    # Payload: list of [temp, speed] pairs (lists, not tuples, for JSON compat)
    curve_edited = Signal(list)

    def __init__(self, parent=None):
        self._fig = Figure(figsize=(4.5, 2.8), dpi=96, tight_layout=True)
        self._fig.patch.set_facecolor(_C_AXBG)
        self._ax = self._fig.add_subplot(111)
        super().__init__(self._fig)
        self.setParent(parent)
        _configure_axes(self._ax)
        self._draw_placeholder()

        # Custom-mode / interactivity state
        self._custom_points: list[tuple[int, int]] = list(DEFAULT_CUSTOM_CURVE)
        self._interactive: bool = False
        self._drag_idx: int | None = None
        self._cids: list = []
        self._current_mode: str = ""   # last mode passed to update_curve

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def update_curve(self, mode: str, target_pct: int = 75) -> None:
        """
        Redraw the chart to show the curve for *mode*.

        Called by main.py when:
          - the user selects a radio button
          - a mode is successfully applied
          - the EC mode changes (auto-refresh, but only mode label, not live data)

        target_pct is only used for Fix / AutoMax modes.
        """
        self._current_mode = mode
        self._render(mode, target_pct)

    def set_interactive(self, enabled: bool, points: list | None = None) -> None:
        """Enter or leave drag-to-edit mode for the Custom curve."""
        if points:
            validated = [(int(p[0]), int(p[1])) for p in points]
            if _validate_curve(validated):
                self._custom_points = validated

        self._interactive = enabled

        for cid in self._cids:
            try:
                self._fig.canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._cids.clear()
        self._drag_idx = None

        if enabled:
            self._cids = [
                self._fig.canvas.mpl_connect("button_press_event",   self._on_press),
                self._fig.canvas.mpl_connect("motion_notify_event",  self._on_motion),
                self._fig.canvas.mpl_connect("button_release_event", self._on_release),
            ]
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.setToolTip(
                "Drag the amber points to reshape the custom fan curve.\n"
                "Temperature: 0–105 °C  ·  Fan speed: 0–100 %\n"
                "Note: the EC enforces a minimum of 30 % when applied."
            )
        else:
            self.unsetCursor()
            self.setToolTip("")

    def set_custom_points(self, points: list) -> None:
        """Load breakpoints from settings (called at startup)."""
        validated = [(int(p[0]), int(p[1])) for p in points]
        if _validate_curve(validated):
            self._custom_points = validated

    def get_custom_points(self) -> list[tuple[int, int]]:
        return list(self._custom_points)

    def is_dragging(self) -> bool:
        return self._drag_idx is not None

    # ------------------------------------------------------------------ #
    # Rendering                                                            #
    # ------------------------------------------------------------------ #

    def _render(self, mode: str, target_pct: int = 75) -> None:
        """Full redraw — curve shape only, no live data overlays."""
        ax = self._ax
        ax.cla()
        _configure_axes(ax)

        if mode == "Custom mode":
            pts = self._custom_points
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            t_dense = np.linspace(min(xs), max(xs), 300)
            s_dense = np.interp(t_dense, xs, ys)
            ax.plot(t_dense, s_dense, color=_C_CUSTOM, linewidth=2.5,
                    linestyle="--", label="Custom curve", zorder=3)
            ax.fill_between(t_dense, 0, s_dense,
                            color=_C_CUSTOM, alpha=0.10, zorder=2)
            handle_s     = 80  if self._interactive else 32
            handle_c     = _C_HANDLE if self._interactive else _C_CUSTOM
            handle_ec    = "#fff" if self._interactive else handle_c
            handle_lw    = 1.0  if self._interactive else 0.0
            ax.scatter(xs, ys, color=handle_c, s=handle_s, zorder=6,
                       clip_on=False, edgecolors=handle_ec, linewidths=handle_lw)
            suffix = "  ✏ drag points to edit" if self._interactive else ""
            ax.set_title(f"Fan Curve — Custom{suffix}",
                         color=_C_CUSTOM, fontsize=10, pad=6)
            ax.legend(fontsize=8, loc="upper left",
                      facecolor="#1A2838", edgecolor="#2A3A4A", labelcolor=_C_TEXT)

        elif mode in CURVES:
            pts = CURVES[mode]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            t_dense = np.linspace(min(xs), max(xs), 300)
            s_dense = np.interp(t_dense, xs, ys)
            ax.plot(t_dense, s_dense, color=_C_CURVE, linewidth=2.5,
                    label=mode, zorder=3)
            ax.fill_between(t_dense, 0, s_dense,
                            color=_C_CURVE, alpha=0.12, zorder=2)
            ax.scatter(xs, ys, color=_C_CURVE, s=32, zorder=5, clip_on=False)
            ax.set_title(f"Fan Curve — {mode}", color=_C_TEXT, fontsize=10, pad=6)
            ax.legend(fontsize=8, loc="upper left",
                      facecolor="#1A2838", edgecolor="#2A3A4A", labelcolor=_C_TEXT)

        elif mode in FIXED_SPEED_MODES:
            label = "Target speed" if mode == "Fix mode" else "Max speed (AutoMax)"
            ax.axhline(target_pct, color=_C_CURVE, linewidth=2.5,
                       linestyle="--", label=f"{label}: {target_pct}%", zorder=3)
            if mode == "Auto Max mode":
                ax.axhspan(target_pct, 100, color=_C_CURVE, alpha=0.08, zorder=2)
            ax.set_title(f"Fan Curve — {mode}", color=_C_TEXT, fontsize=10, pad=6)
            ax.legend(fontsize=8, loc="upper left",
                      facecolor="#1A2838", edgecolor="#2A3A4A", labelcolor=_C_TEXT)

        else:
            ax.text(0.5, 0.5, f"No curve data for\n{mode}",
                    transform=ax.transAxes, ha="center", va="center",
                    color=_C_TEXT, fontsize=10)
            ax.set_title(f"Fan Curve — {mode}", color=_C_TEXT, fontsize=10, pad=6)

        self.draw_idle()

    def _redraw_drag(self) -> None:
        """Lightweight redraw called on every mouse-move during a drag."""
        self._render("Custom mode")

    # ------------------------------------------------------------------ #
    # Mouse event handlers (active only when _interactive=True)            #
    # ------------------------------------------------------------------ #

    def _on_press(self, event) -> None:
        if not self._interactive or event.inaxes is not self._ax:
            return
        if event.button != 1 or event.xdata is None or event.ydata is None:
            return

        ax = self._ax
        inv = ax.transData.inverted()
        origin_disp = ax.transData.transform((0.0, 0.0))
        r_data_x = abs(inv.transform(
            (origin_disp[0] + _HIT_RADIUS_PX, origin_disp[1]))[0])
        r_data_y = abs(inv.transform(
            (origin_disp[0], origin_disp[1] + _HIT_RADIUS_PX))[1])
        if r_data_x == 0:
            r_data_x = 1.0
        if r_data_y == 0:
            r_data_y = 1.0

        best_d2, best_i = float("inf"), None
        for i, (tx, ty) in enumerate(self._custom_points):
            dx = (event.xdata - tx) / r_data_x
            dy = (event.ydata - ty) / r_data_y
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2, best_i = d2, i

        if best_d2 <= 1.0 and best_i is not None:
            self._drag_idx = best_i

    def _on_motion(self, event) -> None:
        if self._drag_idx is None or event.inaxes is not self._ax:
            return
        if event.xdata is None or event.ydata is None:
            return

        i   = self._drag_idx
        pts = self._custom_points
        new_y = max(0, min(100, round(event.ydata)))
        x_lo  = pts[i - 1][0] + 1 if i > 0             else 0
        x_hi  = pts[i + 1][0] - 1 if i < len(pts) - 1  else 105
        new_x = max(x_lo, min(x_hi, round(event.xdata)))
        self._custom_points[i] = (new_x, new_y)
        self._redraw_drag()

    def _on_release(self, event) -> None:
        if self._drag_idx is None:
            return
        self._drag_idx = None
        self.curve_edited.emit([[t, s] for t, s in self._custom_points])

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    def _draw_placeholder(self) -> None:
        self._ax.text(
            0.5, 0.5, "Waiting for data…",
            transform=self._ax.transAxes,
            ha="center", va="center",
            color=_C_TEXT, fontsize=11,
        )
        self.draw()


# ---------------------------------------------------------------------------
# FanStatusWidget — live status chart (right panel)
# ---------------------------------------------------------------------------

class FanStatusWidget(FigureCanvasQTAgg):
    """
    Read-only chart showing the live fan speeds and CPU/GPU temperatures.

    Updated on every auto-refresh tick.  Shows:
      • The active mode's curve as a dim background (context)
      • Fan 0 speed — horizontal orange line
      • Fan 1 speed — horizontal lighter-orange line
      • CPU temperature — vertical green line
      • GPU temperature — vertical purple line (if available)
      • Operating-point dot — where the CPU temp meets the background curve

    No interactivity.
    """

    def __init__(self, parent=None):
        self._fig = Figure(figsize=(4.5, 2.8), dpi=96, tight_layout=True)
        self._fig.patch.set_facecolor(_C_AXBG)
        self._ax = self._fig.add_subplot(111)
        super().__init__(self._fig)
        self.setParent(parent)
        _configure_axes(self._ax)
        self._draw_placeholder()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def update_status(
        self,
        mode: str,
        fan0_pct: int,
        fan1_pct: int,
        target_pct: int,
        cpu_temp: int | None,
        gpu_temp: int | None = None,
        curve_pts: list | None = None,
    ) -> None:
        """
        Redraw with the latest live readings.

        mode       : currently applied mode label (e.g. "Normal mode")
        fan0_pct   : Fan 0 current speed %
        fan1_pct   : Fan 1 current speed %
        target_pct : target speed % (Fix / AutoMax)
        cpu_temp   : CPU package temperature °C, or None
        gpu_temp   : GPU temperature °C, or None
        curve_pts  : explicit breakpoints to use as background curve; supply
                     these when custom mode is active so the custom curve is
                     shown instead of looking up CURVES[mode]
        """
        ax = self._ax
        ax.cla()
        _configure_axes(ax)

        # ---- Background curve (dim) ------------------------------------
        bg_pts = self._resolve_curve(mode, target_pct, curve_pts)

        if bg_pts is not None:
            xs = [p[0] for p in bg_pts]
            ys = [p[1] for p in bg_pts]
            t_dense = np.linspace(min(xs), max(xs), 300)
            s_dense = np.interp(t_dense, xs, ys)
            bg_color = _C_CUSTOM if mode == "Custom mode" else _C_CURVE
            ax.plot(t_dense, s_dense, color=bg_color, linewidth=1.5,
                    alpha=0.25, zorder=2)
            ax.fill_between(t_dense, 0, s_dense, color=bg_color,
                            alpha=0.06, zorder=1)

            # Operating-point dot: where the CPU temp sits on the background curve
            if cpu_temp is not None and len(xs) >= 2:
                interp_speed = float(np.interp(cpu_temp, xs, ys))
                ax.scatter([cpu_temp], [interp_speed],
                           color=_C_POINT, s=50, zorder=7,
                           edgecolors="#fff", linewidths=0.8,
                           label=f"Curve @ {cpu_temp}°C → {interp_speed:.0f}%")

        elif mode in FIXED_SPEED_MODES:
            ax.axhline(target_pct, color=_C_CURVE, linewidth=1.5,
                       linestyle="--", alpha=0.3, zorder=2)

        # ---- Fan speed overlays ----------------------------------------
        ax.axhline(fan0_pct, color=_C_CURRENT, linewidth=1.8,
                   linestyle="-", zorder=4,
                   label=f"Fan 0  {fan0_pct}%")
        ax.axhline(fan1_pct, color=_C_FAN1, linewidth=1.8,
                   linestyle="--", zorder=4,
                   label=f"Fan 1  {fan1_pct}%")

        # ---- Temperature overlays --------------------------------------
        if cpu_temp is not None:
            ax.axvline(cpu_temp, color=_C_CPU_TEMP, linewidth=1.5,
                       linestyle=":", zorder=5,
                       label=f"CPU  {cpu_temp} °C")

        if gpu_temp is not None:
            ax.axvline(gpu_temp, color=_C_GPU_TEMP, linewidth=1.5,
                       linestyle=":", zorder=5,
                       label=f"GPU  {gpu_temp} °C")

        # ---- Legend & title --------------------------------------------
        ax.set_title(f"Live Status — {mode}", color=_C_TEXT, fontsize=10, pad=6)
        ax.legend(
            fontsize=8, loc="upper left",
            facecolor="#1A2838", edgecolor="#2A3A4A",
            labelcolor=_C_TEXT,
        )

        self.draw_idle()

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    def _resolve_curve(
        self,
        mode: str,
        target_pct: int,
        curve_pts: list | None,
    ) -> list | None:
        """Return the breakpoint list to use as the background curve, or None."""
        if curve_pts is not None:
            validated = [(int(p[0]), int(p[1])) for p in curve_pts]
            if _validate_curve(validated):
                return validated
        if mode in CURVES:
            return CURVES[mode]
        return None  # Fix / AutoMax / unknown handled separately

    def _draw_placeholder(self) -> None:
        self._ax.text(
            0.5, 0.5, "Waiting for data…",
            transform=self._ax.transAxes,
            ha="center", va="center",
            color=_C_TEXT, fontsize=11,
        )
        self.draw()
