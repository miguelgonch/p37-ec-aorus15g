#!/usr/bin/env bash
# install.sh — Deploy the AORUS Fan Control bundle to /opt/ and register it
#              as a system desktop application.
#
# Usage (from anywhere, must run as root or with sudo):
#   sudo bash packaging/install.sh
#
# Prerequisites:
#   1. The DKMS ec_io module must already be installed (bash dkms/install.sh)
#   2. The PyInstaller bundle must already be built   (bash packaging/build.sh)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="$REPO_ROOT/dist/aorus-fan-control"
INSTALL_DIR="/opt/aorus-fan-control"
DESKTOP_DIR="/usr/share/applications"
POLKIT_DIR="/usr/share/polkit-1/actions"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

if [ ! -d "$BUNDLE" ]; then
    echo "ERROR: Bundle not found at $BUNDLE" >&2
    echo "       Run 'bash packaging/build.sh' first." >&2
    exit 1
fi

# ── Install bundle ─────────────────────────────────────────────────────────────
echo "==> Installing bundle → $INSTALL_DIR"
rm -rf "$INSTALL_DIR"
cp -r "$BUNDLE" "$INSTALL_DIR"
chown -R root:root "$INSTALL_DIR"
# Main launcher must be executable; the _internal/ binaries keep their bits
chmod 755 "$INSTALL_DIR/aorus-fan-control"

# ── Desktop entry ──────────────────────────────────────────────────────────────
echo "==> Installing .desktop file → $DESKTOP_DIR"
cp "$REPO_ROOT/packaging/aorus-fan-control.desktop" "$DESKTOP_DIR/"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# ── Polkit action ──────────────────────────────────────────────────────────────
if [ -d "$POLKIT_DIR" ]; then
    echo "==> Installing polkit action → $POLKIT_DIR"
    cp "$REPO_ROOT/packaging/com.github.aorus-fan-control.policy" "$POLKIT_DIR/"
else
    echo "    (polkit actions directory not found — skipping policy install)"
fi

echo ""
echo "==> Installation complete."
echo "    Launch:  AORUS Fan Control  (in your system app menu)"
echo "    Or run:  /opt/aorus-fan-control/aorus-fan-control"
echo ""
echo "    A graphical password dialog will appear on first launch."
