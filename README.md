# Alfred Platform

A unified monorepo that combines three services into a single platform accessible via one web interface:

- **Alfred** — WhatsApp AI assistant (gateway + bridge)
- **OurCents** — Family expense tracker with receipt scanning
- **Nudge** — Natural language reminder service

## Architecture

```
alfred-platform/
├── bridge/           # Node.js WhatsApp Web bridge (port 3001)
├── services/
│   ├── gateway/      # Python FastAPI — Alfred backend + serves frontend (port 8000)
│   ├── ourcents/     # Python FastAPI — OurCents backend (port 8001)
│   └── nudge/        # Python FastAPI — Nudge backend (port 8002)
├── shared/           # Shared Python auth package (JWT, password hashing)
├── web/              # React 19 unified frontend (built into gateway)
├── data/             # SQLite databases + uploaded files (git-ignored)
├── config/           # Service configuration (services.yaml)
├── docker-compose.yml
└── .env              # All secrets and config (copy from .env.example)
```

The frontend is built into the gateway Docker image. In production, visiting `http://localhost:8000` serves the full React app.

## Prerequisites

- Docker and Docker Compose
- (For local dev only) Node.js 22+, Python 3.11+

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key used by all three services |
| `SECRET_KEY` | Yes | JWT signing secret — use a long random string |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Yes | Alfred gateway admin login |
| `BRIDGE_API_KEY` | Yes | Internal key between bridge and gateway |
| `WHATSAPP_ACCESS_TOKEN` | Only for cloud WhatsApp API mode | Meta WhatsApp Cloud API token |

### 2. Start the platform

```bash
docker-compose up --build
```

First run builds all images (takes a few minutes). Subsequent starts are faster:

```bash
docker-compose up
```

### 3. Open the app

Visit **http://localhost:8000** in your browser.

Login with the `ADMIN_USERNAME` / `ADMIN_PASSWORD` you set in `.env`.

## Stopping the platform

**Stop (keep data):**
```bash
docker-compose down
```

**Stop and remove all containers + network (keep data):**
```bash
docker-compose down --remove-orphans
```

**Stop and wipe everything including data volumes:**
```bash
docker-compose down -v
# WARNING: this deletes all SQLite databases and uploaded receipts
```

## Running individual services

Start only specific services:
```bash
docker-compose up bridge gateway        # Alfred only
docker-compose up ourcents              # OurCents only
docker-compose up nudge                 # Nudge only
```

Restart a single service without rebuilding others:
```bash
docker-compose restart gateway
```

Rebuild and restart one service after a code change:
```bash
docker-compose up --build gateway
```

## Logs

All services:
```bash
docker-compose logs -f
```

Single service:
```bash
docker-compose logs -f gateway
docker-compose logs -f ourcents
docker-compose logs -f nudge
docker-compose logs -f bridge
```

## Service URLs

| Service | URL | Notes |
|---|---|---|
| Web app | http://localhost:8000 | Main entry point |
| Gateway API docs | http://localhost:8000/docs | Swagger UI |
| OurCents API docs | http://localhost:8001/docs | Swagger UI |
| Nudge API docs | http://localhost:8002/docs | Swagger UI |
| Bridge sessions | http://localhost:3001/sessions | WhatsApp Web status |

## Local development (without Docker)

Each Python service has its own virtual environment under `services/<name>/.venv`.
They are already created and populated — no setup needed on first clone, just activate and run.

### Virtual environment locations

| Service | venv path | Python interpreter |
|---|---|---|
| gateway | `services/gateway/.venv` | `services/gateway/.venv/bin/python` |
| ourcents | `services/ourcents/.venv` | `services/ourcents/.venv/bin/python` |
| nudge | `services/nudge/.venv` | `services/nudge/.venv/bin/python` |

> **VSCode**: open each service folder and select the matching interpreter via
> `Cmd+Shift+P → Python: Select Interpreter`.

### Starting all services locally

Open five terminal tabs from the repo root:

```bash
# Tab 1 — bridge (Node.js)
cd bridge && node src/server.mjs

# Tab 2 — gateway  (serves frontend + Alfred API)
source services/gateway/.venv/bin/activate
uvicorn app.main:app --reload --port 8000 --app-dir services/gateway

# Tab 3 — ourcents
source services/ourcents/.venv/bin/activate
uvicorn main:app --reload --port 8001 --app-dir services/ourcents

# Tab 4 — nudge
source services/nudge/.venv/bin/activate
uvicorn main:app --reload --port 8002 --app-dir services/nudge

# Tab 5 — frontend dev server (hot reload)
cd web && npm run dev     # http://localhost:5173
```

### Stopping local services

`Ctrl+C` in each terminal tab. If a port stays occupied:
```bash
lsof -ti :8000 | xargs kill   # replace port as needed
```

### Re-creating venvs from scratch

```bash
# From repo root
python3 -m venv services/gateway/.venv
services/gateway/.venv/bin/pip install -e ./shared -e ./services/gateway

python3 -m venv services/ourcents/.venv
services/ourcents/.venv/bin/pip install -e ./shared -r ./services/ourcents/requirements.txt

python3 -m venv services/nudge/.venv
services/nudge/.venv/bin/pip install -e ./shared -r ./services/nudge/requirements.txt
```

### Frontend

```bash
cd web
npm install   # first time only — node_modules already present
npm run dev   # dev server on http://localhost:5173
```

In dev mode the frontend talks directly to the backend ports (8000/8001/8002).
In production (`docker-compose up`) everything is served through port 8000.

## Data

All persistent data is stored in `./data/` (mounted into containers as `/data`):

```
data/
├── alfred.db          # Alfred conversations, connections, users
├── ourcents.db        # OurCents families, users, receipts
├── nudge.db           # Nudge reminders
├── receipts/          # Uploaded receipt images
└── temp/              # Temporary upload staging
```

Back up this directory to preserve all application data.

## WhatsApp setup

Alfred supports two WhatsApp modes, set via `WHATSAPP_MODE` in `.env`:

- `bridge` (default) — Uses the local Node.js bridge connecting to WhatsApp Web. Scan the QR code printed in the bridge logs on first run.
- `cloud` — Uses the Meta WhatsApp Cloud API. Requires `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`.
