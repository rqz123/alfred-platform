#!/usr/bin/env bash
set -e

REPO="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$REPO/.pids"
LOG_DIR="$REPO/.logs"

# ── Preflight checks ──────────────────────────────────────────────────────────

if [ ! -f "$REPO/.env" ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in your values:"
  echo "  cp .env.example .env"
  exit 1
fi

if [ -f "$PID_FILE" ]; then
  echo "ERROR: Services appear to already be running (.pids file exists)."
  echo "  Run ./stop.sh first, or delete .pids if processes are gone."
  exit 1
fi

mkdir -p "$LOG_DIR"

# ── Load .env ─────────────────────────────────────────────────────────────────
set -a
# shellcheck disable=SC1091
source "$REPO/.env"
set +a

# ── Start services (nohup so they survive terminal close) ─────────────────────

echo "Starting Alfred Platform..."
echo ""

# Bridge (Node.js)
echo "  [1/5] bridge       → http://localhost:3001"
cd "$REPO/bridge"
nohup node src/server.mjs > "$LOG_DIR/bridge.log" 2>&1 &
echo $! >> "$PID_FILE"

# Gateway (Python — serves frontend in prod mode)
echo "  [2/5] gateway      → http://localhost:8000"
cd "$REPO/services/gateway"
nohup "$REPO/services/gateway/.venv/bin/uvicorn" app.main:app \
  --host 0.0.0.0 --port 8000 --reload \
  > "$LOG_DIR/gateway.log" 2>&1 &
echo $! >> "$PID_FILE"

# OurCents
echo "  [3/5] ourcents     → http://localhost:8001"
cd "$REPO/services/ourcents"
nohup "$REPO/services/ourcents/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port 8001 --reload \
  > "$LOG_DIR/ourcents.log" 2>&1 &
echo $! >> "$PID_FILE"

# Nudge
echo "  [4/5] nudge        → http://localhost:8002"
cd "$REPO/services/nudge"
nohup "$REPO/services/nudge/.venv/bin/uvicorn" main:app \
  --host 0.0.0.0 --port 8002 --reload \
  > "$LOG_DIR/nudge.log" 2>&1 &
echo $! >> "$PID_FILE"

# Frontend dev server
echo "  [5/5] frontend     → http://localhost:5173"
cd "$REPO/web"
nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
echo $! >> "$PID_FILE"

cd "$REPO"

# ── Wait and verify ───────────────────────────────────────────────────────────

echo ""
echo "All services started. Waiting for them to initialize..."
sleep 10

# Quick health check (use 127.0.0.1 to avoid IPv6 resolution issues)
FAILED=0
curl -sf http://127.0.0.1:8000/docs             > /dev/null 2>&1 || { echo "  ✗ gateway failed — check .logs/gateway.log";  FAILED=1; }
curl -sf http://127.0.0.1:8001/api/ourcents/health > /dev/null 2>&1 || { echo "  ✗ ourcents failed — check .logs/ourcents.log"; FAILED=1; }
curl -sf http://127.0.0.1:8002/api/nudge/health  > /dev/null 2>&1 || { echo "  ✗ nudge failed — check .logs/nudge.log";    FAILED=1; }
curl -sf http://127.0.0.1:3001/health            > /dev/null 2>&1 || { echo "  ✗ bridge failed — check .logs/bridge.log";   FAILED=1; }

if [ $FAILED -eq 0 ]; then
  echo ""
  echo "  ✓ All services healthy"
fi

echo ""
echo "  App:      http://localhost:8000       (gateway + frontend)"
echo "  Frontend: http://localhost:5173       (hot-reload dev server)"
echo "  OurCents: http://localhost:8001/docs"
echo "  Nudge:    http://localhost:8002/docs"
echo ""
echo "Logs: .logs/   (tail -f .logs/gateway.log)"
echo "Stop: ./stop.sh"
