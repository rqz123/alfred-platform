#!/usr/bin/env bash
# Backup Gateway whatsappconnection DB rows + Bridge .wwebjs_auth profiles.
# Safe to run at any time; never modifies any state.
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
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_DIR="$REPO/data/backups/gateway-connection-${TIMESTAMP}"

mkdir -p "$BACKUP_DIR"

echo "=== Gateway Connection Backup ==="
echo "Backup dir: $BACKUP_DIR"
echo ""

# 1. Dump whatsappconnection rows to JSON
python3 - "$DB_PATH" "$BACKUP_DIR" << 'PYEOF'
import sys, sqlite3, json
db_path, backup_dir = sys.argv[1], sys.argv[2]
db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row
rows = [dict(r) for r in db.execute("SELECT * FROM whatsappconnection")]
with open(f"{backup_dir}/connection.json", "w") as f:
    json.dump(rows, f, indent=2, default=str)
print(f"Saved {len(rows)} connection row(s) to connection.json")
for r in rows:
    print(f"  id={r['id']}  session={r['bridge_session_id']}  label={r.get('label')}")
PYEOF

# 2. Merge live Bridge status into snapshot
LIVE_JSON=$(curl -sf -H "X-Bridge-Key: ${BRIDGE_API_KEY}" "${BRIDGE_URL}/sessions" 2>/dev/null || echo "[]")

python3 - "$BACKUP_DIR" "$LIVE_JSON" << 'PYEOF'
import sys, json
backup_dir, live_raw = sys.argv[1], sys.argv[2]
rows = json.load(open(f"{backup_dir}/connection.json"))
live_map = {s["id"]: s for s in json.loads(live_raw)}
for row in rows:
    row["live_status"] = live_map.get(row["bridge_session_id"], {})
with open(f"{backup_dir}/connection.json", "w") as f:
    json.dump(rows, f, indent=2, default=str)
for row in rows:
    s = row["live_status"].get("status", "unknown (Bridge not responding)")
    phone = row["live_status"].get("connected_phone", "")
    print(f"  Bridge status: {s}{' (+' + phone + ')' if phone else ''}")
PYEOF

# 3. Copy .wwebjs_auth session directories
SESSION_IDS=$(python3 - "$BACKUP_DIR" << 'PYEOF'
import sys, json
rows = json.load(open(f"{sys.argv[1]}/connection.json"))
print(" ".join(r["bridge_session_id"] for r in rows))
PYEOF
)

mkdir -p "$BACKUP_DIR/wwebjs_auth"
for sid in $SESSION_IDS; do
    src="$WWEBJS_AUTH/session-$sid"
    if [ -d "$src" ]; then
        cp -r "$src" "$BACKUP_DIR/wwebjs_auth/session-$sid"
        echo "Copied auth profile: session-$sid"
    else
        echo "WARNING: auth profile missing for session-$sid"
    fi
    # Optionally copy cache
    if [ -d "$WWEBJS_AUTH/../.wwebjs_cache/session-$sid" ]; then
        mkdir -p "$BACKUP_DIR/wwebjs_cache"
        cp -r "$WWEBJS_AUTH/../.wwebjs_cache/session-$sid" "$BACKUP_DIR/wwebjs_cache/session-$sid"
    fi
done

echo ""
echo "Backup complete: $BACKUP_DIR"
