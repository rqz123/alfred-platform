import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import create_tables
from routers.brain import router as brain_router
from services import qdrant_service
from services.trigger_monitor import (
    on_startup_misfire_check,
    run_trigger_monitor,
    scan_awaiting_timeouts,
    update_geofence_heartbeat,
)
from services.proactive_nudge import run_proactive_nudge_all

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brain")

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
FRONTEND_ORIGIN_ALT = os.environ.get("FRONTEND_ORIGIN_ALT", "http://127.0.0.1:5173")

_scheduler = BackgroundScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    create_tables()
    if settings.qdrant_enabled:
        qdrant_service.ensure_collections()
        logger.info("Qdrant collections ready at %s", settings.qdrant_url)
    else:
        logger.warning("Qdrant disabled (QDRANT_ENABLED=false)")

    # Run misfire check once at startup before starting the scheduler
    try:
        on_startup_misfire_check()
    except Exception as exc:
        logger.warning("Startup misfire check failed (non-fatal): %s", exc)

    # Register periodic workers
    _scheduler.add_job(run_trigger_monitor, "interval", seconds=60, id="trigger_monitor")
    _scheduler.add_job(scan_awaiting_timeouts, "interval", seconds=60, id="awaiting_timeouts")
    _scheduler.add_job(run_proactive_nudge_all, "cron", hour=9, minute=0, id="proactive_nudge")
    _scheduler.add_job(update_geofence_heartbeat, "interval", seconds=300, id="geofence_heartbeat")
    _scheduler.start()
    logger.info("Brain service started — scheduler running")

    yield

    _scheduler.shutdown(wait=False)
    logger.info("Brain service stopped")


app = FastAPI(title="Brain API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_ORIGIN,
        FRONTEND_ORIGIN_ALT,
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(brain_router, prefix="/api/brain")
