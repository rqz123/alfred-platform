#!/usr/bin/env bash
REPO="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$REPO/.env" ]; then
  echo "ERROR: .env not found."
  exit 1
fi

# shellcheck disable=SC1091
source "$REPO/.env"

GW="${GATEWAY_PORT:-8000}"
OC="${OURCENTS_PORT:-8001}"
NU="${NUDGE_PORT:-8002}"
BR="${BRIDGE_PORT:-3001}"

check() {
    local name=$1 port=$2 url=$3
    if curl -sf --max-time 2 "$url" > /dev/null 2>&1; then
        echo "  ✓ ${name}  :${port}"
    else
        echo "  ✗ ${name}  :${port}  (not responding)"
    fi
}

echo "Alfred Platform — Service Status"
echo ""
check "gateway " "$GW" "http://127.0.0.1:${GW}/health"
check "ourcents" "$OC" "http://127.0.0.1:${OC}/api/ourcents/health"
check "nudge   " "$NU" "http://127.0.0.1:${NU}/api/nudge/health"
check "bridge  " "$BR" "http://127.0.0.1:${BR}/health"

# wa-sim daemon
PID_FILE="$REPO/wa-sim/wa-sim.pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "  ✓ wa-sim   (daemon PID ${PID})"
    else
        echo "  ✗ wa-sim   (stale PID ${PID} — run: ./wa-sim/kill.sh)"
    fi
else
    echo "  - wa-sim   (not running)"
fi

echo ""
echo "Ports (from .env):"
echo "  GATEWAY_PORT=${GW}  OURCENTS_PORT=${OC}  NUDGE_PORT=${NU}  BRIDGE_PORT=${BR}"
echo "  BRIDGE_API_URL=${BRIDGE_API_URL:-not set}"
