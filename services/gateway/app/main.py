from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    auth_router,
    connection_router,
    conversation_router,
    internal_router,
    message_router,
)
from app.api.webhooks import webhook_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.seed import seed_data
from app.db.session import get_session, init_db
from app.repositories.connection_repository import list_connections
from app.services.bridge_service import create_bridge_session
from app.services.media_service import ensure_media_dir


configure_logging()
logger = logging.getLogger("alfred.app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting Alfred backend")
    init_db()
    seed_data()
    ensure_media_dir()
    _reinit_bridge_sessions()
    logger.info("Alfred backend startup complete")
    yield
    logger.info("Stopping Alfred backend")


def _reinit_bridge_sessions() -> None:
    try:
        with next(get_session()) as session:
            connections = list_connections(session)
        for conn in connections:
            try:
                create_bridge_session(conn.bridge_session_id)
                logger.info("Re-initialized bridge session %s", conn.bridge_session_id)
            except Exception as exc:
                logger.warning("Could not re-initialize bridge session %s: %s", conn.bridge_session_id, exc)
    except Exception as exc:
        logger.warning("Bridge session re-init skipped: %s", exc)


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, settings.frontend_origin_alt],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api")
app.include_router(connection_router, prefix="/api")
app.include_router(conversation_router, prefix="/api")
app.include_router(internal_router, prefix="/api")
app.include_router(message_router, prefix="/api")
app.include_router(webhook_router)

# Serve built React frontend in production
_DIST_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "dist")
if os.path.isdir(_DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa():
        return FileResponse(os.path.join(_DIST_DIR, "index.html"))
