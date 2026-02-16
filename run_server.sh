#!/bin/bash
#
# One-shot launcher for WebRTC server.
#

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
START_SCRIPT="${ROOT_DIR}/start_webrtc_server.sh"

if [[ ! -x "${START_SCRIPT}" ]]; then
  echo "Error: ${START_SCRIPT} is not executable"
  exit 1
fi

# Align with QEMU launcher socket name.
export SOCKET_PATH="${SOCKET_PATH:-/tmp/qemu_dbus.sock}"

# Ignore stale ICE config from previous shells.
unset QEMU_WEBRTC_ICE_SERVERS || true
unset TURN_HOST || true
unset TURN_USERNAME || true
unset TURN_CREDENTIAL || true
unset TURN_TRANSPORTS || true
unset ICE_TRANSPORT_POLICY || true

echo "run_server.sh:"
echo "  SOCKET_PATH=${SOCKET_PATH}"
echo "  STUN_URL=${STUN_URL:-stun:stun.l.google.com:19302}"

exec "${START_SCRIPT}"
