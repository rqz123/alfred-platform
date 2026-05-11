#!/usr/bin/env bash

REPO="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$REPO/.pids"
LOG_DIR="$REPO/.logs"

# ── Preflight checks ──────────────────────────────────────────────────────────

if [ ! -f "$REPO/.env" ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in your values:"
  echo "  cp .env.example .env"
  exit 1
fi

# ── Load .env first so port vars are available everywhere ─────────────────────
set -a
# shellcheck disable=SC1091
source "$REPO/.env"
set +a

# Defaults if port vars not set
GATEWAY_PORT="${GATEWAY_PORT:-8000}"
OURCENTS_PORT="${OURCENTS_PORT:-8001}"
THREAD_PORT="${THREAD_PORT:-${NUDGE_PORT:-8002}}"
BRAIN_PORT="${BRAIN_PORT:-8003}"
BRIDGE_PORT="${BRIDGE_PORT:-3001}"

# If .pids exists or ports are already in use, stop first
if [ -f "$PID_FILE" ]; then
  echo "Found existing .pids — stopping previous services first..."
  "$REPO/stop.sh"
  echo ""
fi

BUSY=$(lsof -ti ":${GATEWAY_PORT},:${OURCENTS_PORT},:${THREAD_PORT},:${BRAIN_PORT},:${BRIDGE_PORT}" 2>/dev/null)
if [ -n "$BUSY" ]; then
  echo "Ports still in use — stopping remaining processes..."
  echo "$BUSY" | xargs kill 2>/dev/null || true
  sleep 2
fi

mkdir -p "$LOG_DIR"

# ── Build frontend (so gateway always serves the latest code) ─────────────────
echo "Building frontend..."
cd "$REPO/web"
npm install --silent 2>/dev/null
npm run build --silent 2>&1 | tail -3
echo ""

# ── Start services ────────────────────────────────────────────────────────────
echo "Starting Alfred Platform..."
echo ""

# Bridge (Node.js) — must start with BRIDGE_API_KEY from root .env
echo "  [1/5] bridge       → http://localhost:${BRIDGE_PORT}"
cd "$REPO/bridge"
nohup node src/server.mjs > "$LOG_DIR/bridge.log" 2>&1 &
echo $! >> "$PID_FILE"

# Gateway (Python — serves built frontend)
echo "  [2/5] gateway      → http://localhost:${GATEWAY_PORT}"
cd "$REPO/services/gateway"
nohup "$REPO/services/gateway/.venv/bin/uvicorn" app.main:app \
  --host 0.0.0.0 --port "${GATEWAY_PORT}" --reload \
  > "$LOG_DIR/gateway.log" 2>&1 &
echo $! >> "$PID_FILE"

# OurCents
echo "  [3/5] ourcents     → http://localhost:${OURCENTS_PORT}"
cd "$REPO/services/ourcents"
nohup "$REPO/services/ourcents/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port "${OURCENTS_PORT}" --reload \
  > "$LOG_DIR/ourcents.log" 2>&1 &
echo $! >> "$PID_FILE"

# Thread
echo "  [4/5] thread       → http://localhost:${THREAD_PORT}"
cd "$REPO/services/thread"
nohup "$REPO/services/thread/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port "${THREAD_PORT}" --reload \
  > "$LOG_DIR/thread.log" 2>&1 &
echo $! >> "$PID_FILE"

# Brain
echo "  [5/5] brain        → http://localhost:${BRAIN_PORT}"
cd "$REPO/services/brain"
nohup "$REPO/services/brain/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port "${BRAIN_PORT}" --reload \
  > "$LOG_DIR/brain.log" 2>&1 &
echo $! >> "$PID_FILE"

cd "$REPO"

# ── Wait and health check ─────────────────────────────────────────────────────
echo ""
echo "Waiting for services to initialize..."
sleep 20

# All services use retry loop — each polls for up to 30s
_wait_for() {
  local name=$1 url=$2 log=$3
  for i in $(seq 1 15); do
    if curl -sf --max-time 2 "$url" > /dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "  ✗ ${name} failed — check ${log}"
  return 1
}

FAILED=0
_wait_for "bridge " "http://127.0.0.1:${BRIDGE_PORT}/health"            ".logs/bridge.log"  || FAILED=1
_wait_for "gateway" "http://127.0.0.1:${GATEWAY_PORT}/health"           ".logs/gateway.log" || FAILED=1
_wait_for "ourcents" "http://127.0.0.1:${OURCENTS_PORT}/api/ourcents/health" ".logs/ourcents.log" || FAILED=1
_wait_for "thread " "http://127.0.0.1:${THREAD_PORT}/api/thread/health"  ".logs/thread.log"  || FAILED=1
_wait_for "brain  " "http://127.0.0.1:${BRAIN_PORT}/api/brain/health"   ".logs/brain.log"   || FAILED=1

echo ""
if [ $FAILED -eq 0 ]; then
  echo "  ✓ All services healthy"
else
  echo "  ✗ Some services failed to start (see above)"
fi

echo ""
echo "  App:      http://localhost:${GATEWAY_PORT}"
echo "  OurCents: http://localhost:${OURCENTS_PORT}/docs"
echo "  Thread:   http://localhost:${THREAD_PORT}/docs"
echo "  Brain:    http://localhost:${BRAIN_PORT}/docs"
echo ""
echo "  Logs:  tail -f .logs/gateway.log"
echo "  Stop:  ./stop.sh"
echo "  Status: ./status.sh"
