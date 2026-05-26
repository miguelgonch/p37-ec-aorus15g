#!/usr/bin/env bash
# install.sh — Deploy the AORUS Fan Control bundle to /opt/ and register it
#              as a system desktop application.
#
# Usage — from the source repository (after running packaging/build.sh):
#   sudo bash packaging/install.sh
#
# Usage — from an extracted release tarball:
#   tar -xzf aorus-fan-control-vX.Y.Z-linux-x86_64.tar.gz
#   sudo bash aorus-fan-control/install.sh
#
# Prerequisites:
#   1. The DKMS ec_io module must already be installed (bash dkms/install.sh)
#   2. The PyInstaller bundle must already be built (bash packaging/build.sh)
#      OR the release tarball has been extracted.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Support two layouts:
#   Tarball:     install.sh lives next to bundle/ (the PyInstaller output dir)
#   Source repo: install.sh lives in packaging/, bundle is at ../dist/aorus-fan-control/
if [ -d "$SCRIPT_DIR/bundle" ]; then
    # Tarball extraction layout
    BUNDLE="$SCRIPT_DIR/bundle"
    PACKAGING_DIR="$SCRIPT_DIR"
else
    # Source repository layout
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    BUNDLE="$REPO_ROOT/dist/aorus-fan-control"
    PACKAGING_DIR="$SCRIPT_DIR"
fi

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
    echo "       From the source repo:  run 'bash packaging/build.sh' first." >&2
    echo "       From a release tarball: ensure you extracted the full archive." >&2
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
cp "$PACKAGING_DIR/aorus-fan-control.desktop" "$DESKTOP_DIR/"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# ── Polkit action ──────────────────────────────────────────────────────────────
if [ -d "$POLKIT_DIR" ]; then
    echo "==> Installing polkit action → $POLKIT_DIR"
    cp "$PACKAGING_DIR/com.github.aorus-fan-control.policy" "$POLKIT_DIR/"
else
    echo "    (polkit actions directory not found — skipping policy install)"
fi

echo ""
echo "==> Installation complete."
echo "    Launch:  AORUS Fan Control  (in your system app menu)"
echo "    Or run:  /opt/aorus-fan-control/aorus-fan-control"
echo ""
echo "    A graphical password dialog will appear on first launch."
