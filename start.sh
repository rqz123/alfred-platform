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
NUDGE_PORT="${NUDGE_PORT:-8002}"
BRIDGE_PORT="${BRIDGE_PORT:-3001}"

# If .pids exists or ports are already in use, stop first
if [ -f "$PID_FILE" ]; then
  echo "Found existing .pids — stopping previous services first..."
  "$REPO/stop.sh"
  echo ""
fi

BUSY=$(lsof -ti ":${GATEWAY_PORT},:${OURCENTS_PORT},:${NUDGE_PORT},:${BRIDGE_PORT}" 2>/dev/null)
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
echo "  [1/4] bridge       → http://localhost:${BRIDGE_PORT}"
cd "$REPO/bridge"
nohup node src/server.mjs > "$LOG_DIR/bridge.log" 2>&1 &
echo $! >> "$PID_FILE"

# Gateway (Python — serves built frontend)
echo "  [2/4] gateway      → http://localhost:${GATEWAY_PORT}"
cd "$REPO/services/gateway"
nohup "$REPO/services/gateway/.venv/bin/uvicorn" app.main:app \
  --host 0.0.0.0 --port "${GATEWAY_PORT}" --reload \
  > "$LOG_DIR/gateway.log" 2>&1 &
echo $! >> "$PID_FILE"

# OurCents
echo "  [3/4] ourcents     → http://localhost:${OURCENTS_PORT}"
cd "$REPO/services/ourcents"
nohup "$REPO/services/ourcents/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port "${OURCENTS_PORT}" --reload \
  > "$LOG_DIR/ourcents.log" 2>&1 &
echo $! >> "$PID_FILE"

# Nudge
echo "  [4/4] nudge        → http://localhost:${NUDGE_PORT}"
cd "$REPO/services/nudge"
nohup "$REPO/services/nudge/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port "${NUDGE_PORT}" --reload \
  > "$LOG_DIR/nudge.log" 2>&1 &
echo $! >> "$PID_FILE"

cd "$REPO"

# ── Wait and health check ─────────────────────────────────────────────────────
echo ""
echo "Waiting for services to initialize..."
sleep 15

# Bridge can take longer to start (Node.js cold start) — retry for up to 20s
BRIDGE_UP=0
for i in $(seq 1 10); do
  if curl -sf "http://127.0.0.1:${BRIDGE_PORT}/health" > /dev/null 2>&1; then
    BRIDGE_UP=1; break
  fi
  sleep 2
done

FAILED=0
[ $BRIDGE_UP -eq 1 ] || { echo "  ✗ bridge  failed — check .logs/bridge.log";   FAILED=1; }
curl -sf "http://127.0.0.1:${GATEWAY_PORT}/docs"                > /dev/null 2>&1 || { echo "  ✗ gateway failed — check .logs/gateway.log";  FAILED=1; }
curl -sf "http://127.0.0.1:${OURCENTS_PORT}/api/ourcents/health" > /dev/null 2>&1 || { echo "  ✗ ourcents failed — check .logs/ourcents.log"; FAILED=1; }
curl -sf "http://127.0.0.1:${NUDGE_PORT}/api/nudge/health"      > /dev/null 2>&1 || { echo "  ✗ nudge   failed — check .logs/nudge.log";    FAILED=1; }

echo ""
if [ $FAILED -eq 0 ]; then
  echo "  ✓ All services healthy"
else
  echo "  ✗ Some services failed to start (see above)"
fi

echo ""
echo "  App:      http://localhost:${GATEWAY_PORT}"
echo "  OurCents: http://localhost:${OURCENTS_PORT}/docs"
echo "  Nudge:    http://localhost:${NUDGE_PORT}/docs"
echo ""
echo "  Logs:  tail -f .logs/gateway.log"
echo "  Stop:  ./stop.sh"
echo "  Status: ./status.sh"
