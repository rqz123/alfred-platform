"""
OurCents FastAPI entry point.

Replaces OurCents/app.py (Streamlit) with a proper REST API.
All business logic in services/, domain/, models/, storage/ is unchanged.
"""

import sys
import os
import logging
from contextlib import asynccontextmanager

# Add this directory to sys.path so bare imports (from models.schema import ...)
# work exactly as they did when OurCents/app.py added 'src/' to sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Add monorepo root for shared package (local dev only; Docker installs it)
_monorepo_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
if _monorepo_root not in sys.path:
    sys.path.insert(0, _monorepo_root)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
FRONTEND_ORIGIN_ALT = os.environ.get("FRONTEND_ORIGIN_ALT", "http://127.0.0.1:5173")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Database initialises itself (creates tables) on first instantiation.
    # Import here so sys.path is already patched above.
    from storage.database import Database
    from storage.file_storage import FileStorage

    db_path = os.environ.get("OURCENTS_DATABASE_PATH", "/data/ourcents.db")
    receipts_path = os.environ.get("OURCENTS_RECEIPTS_STORAGE_PATH", "/data/receipts")
    # FileStorage reads TEMP_UPLOAD_PATH from env; bridge the prefixed var
    if "OURCENTS_TEMP_UPLOAD_PATH" in os.environ:
        os.environ.setdefault("TEMP_UPLOAD_PATH", os.environ["OURCENTS_TEMP_UPLOAD_PATH"])

    _app.state.db = Database(db_path)
    _app.state.file_storage = FileStorage(base_path=receipts_path)
    yield


app = FastAPI(title="OurCents API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, FRONTEND_ORIGIN_ALT, "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router, prefix="/api/ourcents")
