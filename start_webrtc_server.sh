#!/bin/bash
#
# WebRTC server start helper (TURN removed)
#

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="${PYTHON_BIN_OVERRIDE:-python3}"
fi

# QEMU D-Bus socket (aligned with QEMU launch script)
SOCKET_PATH="${SOCKET_PATH:-/tmp/qemu_dbus.sock}"
if [[ ! -S "${SOCKET_PATH}" ]]; then
  echo "Error: QEMU D-Bus socket not found: ${SOCKET_PATH}"
  exit 1
fi
export DBUS_SESSION_BUS_ADDRESS="unix:path=${SOCKET_PATH}"

# TURN is intentionally unsupported.
unset QEMU_WEBRTC_ICE_SERVERS || true
unset QEMU_WEBRTC_TURN_HOST || true
unset QEMU_WEBRTC_TURN_USERNAME || true
unset QEMU_WEBRTC_TURN_CREDENTIAL || true
unset QEMU_WEBRTC_TURN_TRANSPORTS || true
export QEMU_WEBRTC_STUN_URL="${STUN_URL:-stun:stun.l.google.com:19302}"
export QEMU_WEBRTC_ICE_TRANSPORT_POLICY="all"

echo "Starting WebRTC server with:"
echo "  DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS}"
echo "  QEMU_WEBRTC_ICE_TRANSPORT_POLICY=${QEMU_WEBRTC_ICE_TRANSPORT_POLICY}"
echo "  QEMU_WEBRTC_STUN_URL=${QEMU_WEBRTC_STUN_URL:-<unset>}"

exec "${PYTHON_BIN}" "${ROOT_DIR}/server/main.py"
