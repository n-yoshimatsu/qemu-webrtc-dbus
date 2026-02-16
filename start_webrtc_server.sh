#!/bin/bash
#
# WebRTC server start helper
# - Sets required environment variables
# - Optionally enables TURN settings
#

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="${PYTHON_BIN_OVERRIDE:-python3}"
fi

# Required for QEMU D-Bus display connection (aligned with QEMU launch script)
SOCKET_PATH="${SOCKET_PATH:-/tmp/qemu_gl_on.sock}"
if [[ ! -S "${SOCKET_PATH}" ]]; then
  echo "Error: QEMU D-Bus socket not found: ${SOCKET_PATH}"
  exit 1
fi
export DBUS_SESSION_BUS_ADDRESS="unix:path=${SOCKET_PATH}"

detect_public_ip() {
  # 1) Explicit env wins
  if [[ -n "${TURN_HOST:-}" ]]; then
    printf '%s\n' "${TURN_HOST}"
    return 0
  fi

  # 2) AWS IMDSv2
  local token
  token="$(curl -fsS -m 2 -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)"
  if [[ -n "${token}" ]]; then
    curl -fsS -m 2 -H "X-aws-ec2-metadata-token: ${token}" \
      "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true
    return 0
  fi

  # 3) AWS IMDSv1 fallback (if enabled)
  curl -fsS -m 2 "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true
}

detect_turn_user_pass() {
  local conf="${TURN_CONF_PATH:-/etc/turnserver.conf}"
  [[ -r "${conf}" ]] || return 1

  # First non-comment "user=username:password" line.
  local line
  line="$(grep -E '^[[:space:]]*user=[^:#]+:.+$' "${conf}" | head -n1 || true)"
  [[ -n "${line}" ]] || return 1

  line="${line#*=}"
  local username="${line%%:*}"
  local password="${line#*:}"

  [[ -n "${username}" && -n "${password}" ]] || return 1
  printf '%s\n' "${username}"$'\t'"${password}"
}

# Optional TURN configuration
# Enable by setting TURN_HOST (or pre-set QEMU_WEBRTC_ICE_SERVERS directly).
if [[ -z "${QEMU_WEBRTC_ICE_SERVERS:-}" ]]; then
  AUTO_TURN_HOST="${AUTO_TURN_HOST:-1}"
  if [[ "${AUTO_TURN_HOST}" != "0" ]]; then
    AUTO_DETECTED_TURN_HOST="$(detect_public_ip || true)"
    if [[ -n "${AUTO_DETECTED_TURN_HOST}" ]]; then
      export TURN_HOST="${TURN_HOST:-${AUTO_DETECTED_TURN_HOST}}"
    fi
  fi
fi

if [[ -n "${TURN_HOST:-}" ]]; then
  if [[ -z "${TURN_USERNAME:-}" || -z "${TURN_CREDENTIAL:-}" ]]; then
    creds="$(detect_turn_user_pass || true)"
    if [[ -n "${creds}" ]]; then
      export TURN_USERNAME="${TURN_USERNAME:-${creds%%$'\t'*}}"
      export TURN_CREDENTIAL="${TURN_CREDENTIAL:-${creds#*$'\t'}}"
    fi
  fi

  export QEMU_WEBRTC_TURN_HOST="${TURN_HOST}"
  export QEMU_WEBRTC_TURN_USERNAME="${TURN_USERNAME:-webrtc}"
  export QEMU_WEBRTC_TURN_CREDENTIAL="${TURN_CREDENTIAL:-}"
  export QEMU_WEBRTC_TURN_TRANSPORTS="${TURN_TRANSPORTS:-udp,tcp}"
  export QEMU_WEBRTC_STUN_URL="${STUN_URL:-stun:stun.l.google.com:19302}"
  export QEMU_WEBRTC_ICE_TRANSPORT_POLICY="${ICE_TRANSPORT_POLICY:-all}"
fi

echo "Starting WebRTC server with:"
echo "  DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS}"
echo "  QEMU_WEBRTC_ICE_TRANSPORT_POLICY=${QEMU_WEBRTC_ICE_TRANSPORT_POLICY:-<unset>}"
if [[ -n "${QEMU_WEBRTC_TURN_HOST:-}" ]]; then
  echo "  QEMU_WEBRTC_TURN_HOST=${QEMU_WEBRTC_TURN_HOST}"
  echo "  QEMU_WEBRTC_TURN_USERNAME=${QEMU_WEBRTC_TURN_USERNAME:-<unset>}"
else
  echo "  QEMU_WEBRTC_TURN_HOST=<unset>"
  echo "  note: set TURN_HOST explicitly or enable AWS IMDS public IP"
fi

exec "${PYTHON_BIN}" "${ROOT_DIR}/server/main.py"
