#!/usr/bin/env bash
# Deploy / update Alfred Platform using Docker Compose.
# Run after each `git push` to apply the latest code changes.
set -e

REPO="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$REPO/.env" ]; then
  echo "ERROR: .env not found."
  echo "  cp .env.example .env   # then fill in your API keys"
  exit 1
fi

echo "Pulling latest code..."
git -C "$REPO" pull

echo ""
echo "Building and starting services..."
docker compose -f "$REPO/docker-compose.yml" up --build -d

echo ""
echo "Waiting for services to initialize (30s)..."
sleep 30

docker compose -f "$REPO/docker-compose.yml" ps

echo ""
echo "  App:     http://$(hostname -I | awk '{print $1}'):8000"
echo "  Logs:    docker compose logs -f [bridge|gateway|ourcents|nudge]"
echo "  Stop:    docker compose down"
echo ""
echo "First-time setup: if WhatsApp is not connected yet:"
echo "  docker compose logs -f bridge   # scan the QR code shown"
