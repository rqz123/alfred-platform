#!/usr/bin/env bash
# Restore Gateway whatsappconnection DB rows + Bridge auth profiles from a backup.
# Never calls Bridge DELETE or Forget Device — uses non-destructive restart only.
#
# Usage:
#   ./scripts/restore-gateway-connection.sh                         # uses latest backup; skips restart if already connected
#   ./scripts/restore-gateway-connection.sh <backup-dir>            # uses named backup
#   ./scripts/restore-gateway-connection.sh [backup-dir] --force-restart  # restart even if already connected
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$REPO/.env" ]; then
  echo "ERROR: $REPO/.env not found."
  exit 1
fi

set -a; source "$REPO/.env"; set +a

BRIDGE_PORT="${BRIDGE_PORT:-3001}"
BRIDGE_URL="http://127.0.0.1:${BRIDGE_PORT}"
DB_PATH="${DATABASE_URL#sqlite:///}"
WWEBJS_AUTH="$REPO/bridge/.wwebjs_auth"
FORCE_RESTART=0

# Parse args: optional backup-dir, optional --force-restart (either order)
BACKUP_DIR=""
for arg in "$@"; do
    if [ "$arg" = "--force-restart" ]; then
        FORCE_RESTART=1
    elif [ -z "$BACKUP_DIR" ]; then
        BACKUP_DIR="$arg"
    fi
done

if [ -z "$BACKUP_DIR" ]; then
    BACKUP_DIR=$(ls -td "$REPO/data/backups/gateway-connection-"* 2>/dev/null | head -1 || true)
fi

if [ -z "$BACKUP_DIR" ] || [ ! -d "$BACKUP_DIR" ]; then
    echo "ERROR: No backup found. Pass a backup path as argument, or run backup-gateway-connection.sh first."
    exit 1
fi

echo "=== Gateway Connection Restore ==="
echo "Backup: $BACKUP_DIR"
[ "$FORCE_RESTART" = "1" ] && echo "Mode: --force-restart"
echo ""

# 1. Restore .wwebjs_auth session directories (only if missing — never overwrite)
for auth_src in "$BACKUP_DIR"/wwebjs_auth/session-*; do
    [ -d "$auth_src" ] || continue
    sid_dir=$(basename "$auth_src")
    dest="$WWEBJS_AUTH/$sid_dir"
    if [ -d "$dest" ]; then
        echo "Auth profile already present: $sid_dir (preserving existing)"
    else
        mkdir -p "$WWEBJS_AUTH"
        cp -r "$auth_src" "$dest"
        echo "Restored auth profile: $sid_dir"
    fi
done

# 2. Upsert whatsappconnection rows into Gateway DB
python3 - "$DB_PATH" "$BACKUP_DIR" << 'PYEOF'
import sys, sqlite3, json

db_path, backup_dir = sys.argv[1], sys.argv[2]
rows = json.load(open(f"{backup_dir}/connection.json"))
db = sqlite3.connect(db_path)

for row in rows:
    sid = row["bridge_session_id"]
    existing = db.execute(
        "SELECT id FROM whatsappconnection WHERE bridge_session_id = ?", (sid,)
    ).fetchone()
    if existing:
        print(f"DB row already exists for session {sid} — skipping.")
    else:
        db.execute(
            "INSERT INTO whatsappconnection (id, bridge_session_id, label, created_at) VALUES (?, ?, ?, ?)",
            (row.get("id"), sid, row.get("label"), row.get("created_at")),
        )
        print(f"Restored DB row: id={row.get('id')} session={sid} label={row.get('label')}")

db.commit()
PYEOF

# 3. For each session: restart only if not already connected (unless --force-restart)
SESSION_IDS=$(python3 - "$BACKUP_DIR" << 'PYEOF'
import sys, json
rows = json.load(open(f"{sys.argv[1]}/connection.json"))
print(" ".join(r["bridge_session_id"] for r in rows))
PYEOF
)

FAILED_SESSIONS=0

for sid in $SESSION_IDS; do
    echo ""
    echo "--- Session: $sid ---"

    # Check current Bridge state
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "X-Bridge-Key: ${BRIDGE_API_KEY}" \
        "${BRIDGE_URL}/sessions/${sid}")

    if [ "$HTTP_CODE" = "404" ]; then
        CURRENT_STATUS="absent"
    else
        RESP=$(curl -sf \
            -H "X-Bridge-Key: ${BRIDGE_API_KEY}" \
            "${BRIDGE_URL}/sessions/${sid}" 2>/dev/null || echo "{}")
        CURRENT_STATUS=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('status','unknown'))" "$RESP")
        CURRENT_PHONE=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('connected_phone','') or '')" "$RESP")
    fi

    # Skip restart if already connected and not forced
    if [ "$CURRENT_STATUS" = "connected" ] && [ "$FORCE_RESTART" = "0" ]; then
        echo "Already connected${CURRENT_PHONE:+  phone: +$CURRENT_PHONE} — skipping restart. (Use --force-restart to override.)"
        continue
    fi

    # Create session in Bridge if absent
    if [ "$HTTP_CODE" = "404" ]; then
        echo "Session not in Bridge — creating..."
        curl -sf -X POST "${BRIDGE_URL}/sessions" \
            -H "X-Bridge-Key: ${BRIDGE_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "{\"session_id\": \"${sid}\"}" > /dev/null
        sleep 3
    fi

    # Non-destructive restart (preserves .wwebjs_auth — never calls DELETE)
    echo "Restarting session (non-destructive, auth preserved)..."
    curl -sf -X POST "${BRIDGE_URL}/sessions/${sid}/restart" \
        -H "X-Bridge-Key: ${BRIDGE_API_KEY}" \
        -H "Content-Type: application/json" > /dev/null

    # Poll up to 30 s for connected status
    echo -n "Waiting for connected"
    FINAL_STATUS=""
    FINAL_PHONE=""
    for i in $(seq 1 15); do
        sleep 2
        RESP=$(curl -sf \
            -H "X-Bridge-Key: ${BRIDGE_API_KEY}" \
            "${BRIDGE_URL}/sessions/${sid}" 2>/dev/null || echo "{}")
        FINAL_STATUS=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('status',''))" "$RESP")
        FINAL_PHONE=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('connected_phone','') or '')" "$RESP")
        if [ "$FINAL_STATUS" = "connected" ]; then
            echo ""
            echo "Connected!${FINAL_PHONE:+  phone: +$FINAL_PHONE}"
            break
        elif [ "$FINAL_STATUS" = "qr_ready" ]; then
            echo ""
            echo "ERROR: Bridge is requesting a QR scan — auth profile missing or expired."
            echo "  Run backup-gateway-connection.sh first, then scan QR once to re-link."
            FAILED_SESSIONS=$((FAILED_SESSIONS + 1))
            break
        fi
        echo -n "."
    done

    if [ "$FINAL_STATUS" != "connected" ] && [ "$FINAL_STATUS" != "qr_ready" ]; then
        echo ""
        echo "ERROR: Not connected after 30 s (status=${FINAL_STATUS}). Check Bridge logs."
        FAILED_SESSIONS=$((FAILED_SESSIONS + 1))
    fi
done

echo ""
if [ "$FAILED_SESSIONS" -gt 0 ]; then
    echo "Restore finished with $FAILED_SESSIONS failed session(s). Check errors above."
    exit 1
fi
echo "Restore complete."
