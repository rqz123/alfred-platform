#!/usr/bin/env bash

REPO="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$REPO/.pids"

if [ ! -f "$PID_FILE" ]; then
  echo "No running services found (.pids file missing)."
  echo "If processes are still running, stop them manually:"
  echo "  lsof -ti :8000,:8001,:8002,:5173,:3001 | xargs kill"
  exit 0
fi

echo "Stopping Alfred Platform..."
echo ""

NAMES=("bridge" "gateway" "ourcents" "nudge" "frontend")
i=0

while IFS= read -r pid; do
  name="${NAMES[$i]:-unknown}"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    echo "  stopped $name (pid $pid)"
  else
    echo "  $name (pid $pid) was already gone"
  fi
  i=$((i + 1))
done < "$PID_FILE"

rm "$PID_FILE"

echo ""
echo "All services stopped."
