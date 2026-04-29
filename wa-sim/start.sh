#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../services/gateway/.venv/bin/activate"
cd "$SCRIPT_DIR"

exec python -m src.main --daemon "$@"
