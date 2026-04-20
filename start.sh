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

# If .pids exists or ports are already in use, stop first
if [ -f "$PID_FILE" ]; then
  echo "Found existing .pids — stopping previous services first..."
  "$REPO/stop.sh"
  echo ""
fi

BUSY=$(lsof -ti :8000,:8001,:8002,:3001 2>/dev/null)
if [ -n "$BUSY" ]; then
  echo "Ports still in use — stopping remaining processes..."
  echo "$BUSY" | xargs kill 2>/dev/null || true
  sleep 2
fi

mkdir -p "$LOG_DIR"

# ── Load .env (must be before any service start so all inherit the vars) ──────
set -a
# shellcheck disable=SC1091
source "$REPO/.env"
set +a

# ── Build frontend (so port 8000 always serves the latest code) ───────────────
echo "Building frontend..."
cd "$REPO/web"
npm run build --silent 2>&1 | tail -3
echo ""

# ── Start services ────────────────────────────────────────────────────────────
echo "Starting Alfred Platform..."
echo ""

# Bridge (Node.js) — must start with BRIDGE_API_KEY from root .env
echo "  [1/4] bridge       → http://localhost:3001"
cd "$REPO/bridge"
nohup node src/server.mjs > "$LOG_DIR/bridge.log" 2>&1 &
echo $! >> "$PID_FILE"

# Gateway (Python — serves built frontend at port 8000)
echo "  [2/4] gateway      → http://localhost:8000"
cd "$REPO/services/gateway"
nohup "$REPO/services/gateway/.venv/bin/uvicorn" app.main:app \
  --host 0.0.0.0 --port 8000 --reload \
  > "$LOG_DIR/gateway.log" 2>&1 &
echo $! >> "$PID_FILE"

# OurCents
echo "  [3/4] ourcents     → http://localhost:8001"
cd "$REPO/services/ourcents"
nohup "$REPO/services/ourcents/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port 8001 --reload \
  > "$LOG_DIR/ourcents.log" 2>&1 &
echo $! >> "$PID_FILE"

# Nudge
echo "  [4/4] nudge        → http://localhost:8002"
cd "$REPO/services/nudge"
nohup "$REPO/services/nudge/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port 8002 --reload \
  > "$LOG_DIR/nudge.log" 2>&1 &
echo $! >> "$PID_FILE"

cd "$REPO"

# ── Wait and health check ─────────────────────────────────────────────────────
echo ""
echo "Waiting for services to initialize..."
sleep 8

FAILED=0
curl -sf http://127.0.0.1:3001/health              > /dev/null 2>&1 || { echo "  ✗ bridge  failed — check .logs/bridge.log";   FAILED=1; }
curl -sf http://127.0.0.1:8000/docs                > /dev/null 2>&1 || { echo "  ✗ gateway failed — check .logs/gateway.log";  FAILED=1; }
curl -sf http://127.0.0.1:8001/api/ourcents/health > /dev/null 2>&1 || { echo "  ✗ ourcents failed — check .logs/ourcents.log"; FAILED=1; }
curl -sf http://127.0.0.1:8002/api/nudge/health    > /dev/null 2>&1 || { echo "  ✗ nudge   failed — check .logs/nudge.log";    FAILED=1; }

echo ""
if [ $FAILED -eq 0 ]; then
  echo "  ✓ All services healthy"
else
  echo "  ✗ Some services failed to start (see above)"
fi

echo ""
echo "  App:      http://localhost:8000"
echo "  OurCents: http://localhost:8001/docs"
echo "  Nudge:    http://localhost:8002/docs"
echo ""
echo "  Logs:  tail -f .logs/gateway.log"
echo "  Stop:  ./stop.sh"
