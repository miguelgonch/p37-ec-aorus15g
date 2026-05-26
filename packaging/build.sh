#!/usr/bin/env bash
# build.sh — Build the AORUS Fan Control GUI as a self-contained PyInstaller bundle.
#
# Usage (from anywhere):
#   bash packaging/build.sh
#
# Output: dist/aorus-fan-control/
set -euo pipefail

# Always operate from the repository root
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── Ensure uv is available ─────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "==> uv not found — installing via the official installer..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # The installer adds ~/.local/bin (or ~/.cargo/bin) to PATH; source the env
    # update so the rest of this script can find uv without a new shell.
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
echo "==> Using uv $(uv --version)"

echo ""
echo "==> Setting up build virtual environment (.venv)..."
# uv auto-detects .venv in the current directory; create it if absent.
[ -d .venv ] || uv venv .venv

echo "==> Installing Python build dependencies into .venv..."
# uv pip picks up the local .venv automatically — no --system needed.
uv pip install --quiet --upgrade pyinstaller PySide6 matplotlib numpy

echo ""
echo "==> Building bundle with PyInstaller..."
.venv/bin/pyinstaller --clean --noconfirm packaging/aorus-fan-control.spec

echo ""
echo "==> Build complete."
echo "    Bundle:  $REPO_ROOT/dist/aorus-fan-control/"
echo ""
echo "Quick smoke-test (requires ec_io module loaded):"
echo "    sudo dist/aorus-fan-control/aorus-fan-control"
echo ""
echo "To install system-wide:"
echo "    sudo bash packaging/install.sh"
