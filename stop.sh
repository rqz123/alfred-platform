#!/usr/bin/env bash

REPO="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$REPO/.pids"
PORTS="8000,8001,8002,3001"

echo "Stopping Alfred Platform..."
echo ""

# Step 1: Kill processes recorded in .pids
if [ -f "$PID_FILE" ]; then
  NAMES=("bridge" "gateway" "ourcents" "nudge" "frontend")
  i=0
  while IFS= read -r pid; do
    name="${NAMES[$i]:-unknown}"
    if kill -0 "$pid" 2>/dev/null; then
      # Kill the whole process group to catch uvicorn reloader + workers
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null
      echo "  stopped $name (pid $pid)"
    else
      echo "  $name (pid $pid) already gone"
    fi
    i=$((i + 1))
  done < "$PID_FILE"
  rm "$PID_FILE"
else
  echo "  (no .pids file)"
fi

# Step 2: Kill anything still holding the known ports (catches orphaned workers)
sleep 1
LEFTOVERS=$(lsof -ti :"$PORTS" 2>/dev/null)
if [ -n "$LEFTOVERS" ]; then
  echo "  cleaning up orphaned processes on ports $PORTS..."
  echo "$LEFTOVERS" | xargs kill 2>/dev/null || true
  sleep 1
fi

# Step 3: Final check
STILL_UP=$(lsof -ti :"$PORTS" 2>/dev/null)
if [ -n "$STILL_UP" ]; then
  echo "  force-killing remaining processes..."
  echo "$STILL_UP" | xargs kill -9 2>/dev/null || true
fi

echo ""
echo "All services stopped."
