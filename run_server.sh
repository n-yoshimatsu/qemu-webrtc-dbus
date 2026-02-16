#!/bin/bash
#
# One-shot launcher for WebRTC server with TURN auto-configuration.
#

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
START_SCRIPT="${ROOT_DIR}/start_webrtc_server.sh"

if [[ ! -x "${START_SCRIPT}" ]]; then
  echo "Error: ${START_SCRIPT} is not executable"
  exit 1
fi

# Align with QEMU launcher socket name.
export SOCKET_PATH="${SOCKET_PATH:-/tmp/qemu_gl_on.sock}"

# Ignore stale JSON ICE config from previous shells.
unset QEMU_WEBRTC_ICE_SERVERS || true

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

# Defaults for TURN path.
export ICE_TRANSPORT_POLICY="${ICE_TRANSPORT_POLICY:-relay}"

if [[ -z "${TURN_HOST:-}" ]]; then
  TURN_HOST="$(detect_public_ip || true)"
  export TURN_HOST
fi

if [[ -z "${TURN_USERNAME:-}" || -z "${TURN_CREDENTIAL:-}" ]]; then
  creds="$(detect_turn_user_pass || true)"
  if [[ -n "${creds}" ]]; then
    export TURN_USERNAME="${TURN_USERNAME:-${creds%%$'\t'*}}"
    export TURN_CREDENTIAL="${TURN_CREDENTIAL:-${creds#*$'\t'}}"
  fi
fi

echo "run_server.sh:"
echo "  SOCKET_PATH=${SOCKET_PATH}"
echo "  TURN_HOST=${TURN_HOST:-<unset>}"
echo "  TURN_USERNAME=${TURN_USERNAME:-<unset>}"
echo "  ICE_TRANSPORT_POLICY=${ICE_TRANSPORT_POLICY}"

exec "${START_SCRIPT}"
