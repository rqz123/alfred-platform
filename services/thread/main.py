"""
Thread Service — manages Unified Thread lifecycle (CRUD + trigger parsing).

NOTE: Trigger firing logic has been moved to Brain's Trigger Monitor (Module 3).
Thread service only manages lifecycle state; Brain activates threads.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import create_tables
from routers.thread import router as thread_router

import os

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
FRONTEND_ORIGIN_ALT = os.environ.get("FRONTEND_ORIGIN_ALT", "http://127.0.0.1:5173")

logger = logging.getLogger("thread")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_tables()
    yield


app = FastAPI(title="Thread API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, FRONTEND_ORIGIN_ALT, "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(thread_router, prefix="/api/thread")
