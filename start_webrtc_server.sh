#!/bin/bash
#
# WebRTC server start helper (simple fixed config)
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

# TURN settings (host auto-detected from AWS IMDS; others fixed defaults)
detect_public_ip() {
  local token
  token="$(curl -fsS -m 2 -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)"
  if [[ -n "${token}" ]]; then
    curl -fsS -m 2 -H "X-aws-ec2-metadata-token: ${token}" \
      "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true
    return 0
  fi
  curl -fsS -m 2 "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true
}

TURN_HOST_VALUE="${TURN_HOST:-}"
if [[ -z "${TURN_HOST_VALUE}" ]]; then
  TURN_HOST_VALUE="$(detect_public_ip || true)"
fi
if [[ -z "${TURN_HOST_VALUE}" ]]; then
  echo "Error: TURN host auto-detection failed. Set TURN_HOST explicitly."
  exit 1
fi

export QEMU_WEBRTC_TURN_HOST="${TURN_HOST_VALUE}"
export QEMU_WEBRTC_TURN_USERNAME="${TURN_USERNAME:-webrtc}"
export QEMU_WEBRTC_TURN_CREDENTIAL="${TURN_CREDENTIAL:-44yoyoyo}"
export QEMU_WEBRTC_TURN_TRANSPORTS="${TURN_TRANSPORTS:-udp,tcp}"
export QEMU_WEBRTC_STUN_URL="${STUN_URL:-stun:stun.l.google.com:19302}"
export QEMU_WEBRTC_ICE_TRANSPORT_POLICY="${ICE_TRANSPORT_POLICY:-relay}"

echo "Starting WebRTC server with:"
echo "  DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS}"
echo "  QEMU_WEBRTC_ICE_TRANSPORT_POLICY=${QEMU_WEBRTC_ICE_TRANSPORT_POLICY:-<unset>}"
echo "  QEMU_WEBRTC_TURN_HOST=${QEMU_WEBRTC_TURN_HOST}"
echo "  QEMU_WEBRTC_TURN_USERNAME=${QEMU_WEBRTC_TURN_USERNAME}"

exec "${PYTHON_BIN}" "${ROOT_DIR}/server/main.py"
