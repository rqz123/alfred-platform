#!/usr/bin/env bash
# One-time local setup: creates Python venvs and installs all dependencies.
# Run once before using start.sh.
set -e

REPO="$(cd "$(dirname "$0")" && pwd)"

echo "Setting up Alfred Platform for local (non-Docker) development..."
echo ""

# ── Gateway ───────────────────────────────────────────────────────────────────
echo "[1/4] Gateway..."
cd "$REPO/services/gateway"
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e "$REPO/shared"
.venv/bin/pip install -e .
echo "      done."

# ── OurCents ──────────────────────────────────────────────────────────────────
echo "[2/4] OurCents..."
cd "$REPO/services/ourcents"
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
echo "      done."

# ── Thread ────────────────────────────────────────────────────────────────────
echo "[3/4] Thread..."
cd "$REPO/services/thread"
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
echo "      done."

# ── Brain ─────────────────────────────────────────────────────────────────────
echo "[4/5] Brain..."
cd "$REPO/services/brain"
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
echo "      done."

# ── Bridge (Node.js) ──────────────────────────────────────────────────────────
echo "[5/5] Bridge (npm install)..."
cd "$REPO/bridge"
npm install
echo "      done."

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "[web] Frontend (npm install)..."
cd "$REPO/web"
npm install
echo "      done."

echo ""
echo "Setup complete. Run ./start.sh to start all services."
