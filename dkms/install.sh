#!/bin/bash
# install.sh — builds and installs the ec_io misc device DKMS module.
# Must be run as root (sudo bash install.sh).
# Creates /dev/ec_io: a seekable raw byte interface to the EC address space
# that works under Secure Boot kernel lockdown (avoids LOCKDOWN_DEBUGFS).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DKMS_NAME="ec-io"
DKMS_VER="1.0"
KERNEL="$(uname -r)"

# --- Remove old ec-sys-write module if present ---
if dkms status ec-sys-write 2>/dev/null | grep -q installed; then
    echo "==> Removing old ec-sys-write DKMS module"
    dkms remove ec-sys-write/1.0 --all 2>/dev/null || true
fi
rm -rf /usr/src/ec-sys-write-1.0
rmmod ec_sys 2>/dev/null || true

# --- Remove blacklist added by previous attempt ---
rm -f /etc/modprobe.d/ec-sys-stock-blacklist.conf

# --- Install new ec-io module ---
echo "==> Copying source to /usr/src/${DKMS_NAME}-${DKMS_VER}/"
mkdir -p /usr/src/${DKMS_NAME}-${DKMS_VER}
cp "$SCRIPT_DIR/ec_io.c"   /usr/src/${DKMS_NAME}-${DKMS_VER}/
cp "$SCRIPT_DIR/Makefile"  /usr/src/${DKMS_NAME}-${DKMS_VER}/
cp "$SCRIPT_DIR/dkms.conf" /usr/src/${DKMS_NAME}-${DKMS_VER}/

echo "==> Adding DKMS module"
dkms add ${DKMS_NAME}/${DKMS_VER} 2>/dev/null || true

echo "==> Building DKMS module (DKMS signs automatically)"
dkms build ${DKMS_NAME}/${DKMS_VER}

echo "==> Installing DKMS module"
dkms install ${DKMS_NAME}/${DKMS_VER}

echo "==> Enrolling DKMS MOK key (if not already enrolled)"
DKMS_MOK="/var/lib/shim-signed/mok/MOK.der"
if mokutil --test-key "$DKMS_MOK" 2>/dev/null | grep -q 'is already enrolled'; then
    echo "    MOK key already enrolled — no reboot needed for key enrollment."
else
    mokutil --import "$DKMS_MOK"
    echo ""
    echo "    *** REBOOT REQUIRED ***"
    echo "    At the blue MOK manager screen:"
    echo "    Enroll MOK → Continue → Yes → enter password → Reboot"
fi

echo ""
echo "==> After reboot (or now if key was already enrolled), load and test:"
echo "    sudo modprobe ec_io"
echo "    sudo ~/Documents/projects/p37-ec-aorus15g/p37ec-aorus15g"
