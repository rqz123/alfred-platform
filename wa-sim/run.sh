#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
GW_DIR="$ROOT_DIR/services/gateway"
ROOT_ENV="$ROOT_DIR/.env"

source "$GW_DIR/.venv/bin/activate"
cd "$SCRIPT_DIR"

# Load root .env so API keys and service config are available when restarting gateway.
# Individual vars can be overridden below as needed.
set -a
# shellcheck disable=SC1090
source "$ROOT_ENV"
set +a

# Read wa-sim fake bridge port directly from wa-sim/.env (not root .env).
# Root .env also has BRIDGE_PORT (for the real node bridge), which was just sourced above.
# We must override it so the Python daemon binds to the wa-sim port, not the real bridge port.
WASIM_PORT="$(grep '^BRIDGE_PORT=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2 || echo 9001)"
WASIM_BRIDGE_URL="http://localhost:${WASIM_PORT}"
export BRIDGE_PORT="$WASIM_PORT"   # override root .env's BRIDGE_PORT for the Python daemon

# Capture the real bridge URL from root .env before we change BRIDGE_API_URL
REAL_BRIDGE_URL="$BRIDGE_API_URL"
GATEWAY_PORT="${GATEWAY_PORT:-8000}"

restart_gateway() {
    local bridge_url="$1"
    pkill -f 'uvicorn app.main:app' 2>/dev/null || true
    sleep 2
    # Export the desired BRIDGE_API_URL so the gateway process inherits it.
    # pydantic-settings reads env vars before .env file, so this overrides .env.
    # Must cd to GW_DIR so pydantic-settings finds the correct ../../.env (root .env).
    export BRIDGE_API_URL="$bridge_url"
    (cd "$GW_DIR" && nohup .venv/bin/uvicorn app.main:app \
        --host 0.0.0.0 --port "${GATEWAY_PORT}" \
        --app-dir "$GW_DIR" > /tmp/gateway.log 2>&1 &)
    sleep 3
}

cleanup() {
    echo ""
    echo "Restoring gateway → real bridge (${REAL_BRIDGE_URL})"
    restart_gateway "$REAL_BRIDGE_URL"
    echo "Gateway restarted with real bridge URL."
}
trap cleanup EXIT

echo "Switching gateway → wa-sim bridge (${WASIM_BRIDGE_URL})"
restart_gateway "$WASIM_BRIDGE_URL"
echo "Gateway ready with wa-sim bridge."

python -m src.main --daemon "$@"
