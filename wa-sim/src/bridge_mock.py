"""
Fake Bridge server that impersonates whatsapp-bridge for the Gateway.

The Gateway calls this server to:
  - Resolve session info: GET /sessions/{id}  → {session_id, connected_phone, status}
  - Send outbound texts:  POST /sessions/{id}/messages/text
  - Send outbound media:  POST /sessions/{id}/messages/media

This server also handles session registration:
  - POST /sessions   → create/retrieve a session
  - GET  /sessions   → list sessions
  - DELETE /sessions/{id} → remove session

Authentication: Gateway sends X-Bridge-Key header; we validate it matches BRIDGE_API_KEY.

Captured replies are published to `reply_queue` (asyncio.Queue) for the UI to consume.
"""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Path, Request, Response
from pydantic import BaseModel

from . import settings

logger = logging.getLogger("wa-sim.bridge")

app = FastAPI(title="wa-sim fake bridge")

# In-memory session registry: session_id → {session_id, connected_phone}
_sessions: dict[str, dict[str, str]] = {}

# Per-phone reply queues: phone → asyncio.Queue[body]
_reply_queues: dict[str, asyncio.Queue[str]] = {}


def get_reply_queue(phone: str) -> asyncio.Queue[str]:
    if phone not in _reply_queues:
        _reply_queues[phone] = asyncio.Queue()
    return _reply_queues[phone]


def init_reply_queues(phones: list[str]) -> None:
    """Pre-register queues for all known phones at startup."""
    for phone in phones:
        _reply_queues.setdefault(phone, asyncio.Queue())


# ── Auth helper ────────────────────────────────────────────────────

def _check_key(x_bridge_key: str | None) -> None:
    if x_bridge_key != settings.BRIDGE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Bridge API key")


# ── Pydantic schemas ───────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    session_id: str
    connected_phone: str = ""   # simulator sets this so Gateway can resolve the phone


class TextMessageRequest(BaseModel):
    recipient_phone: str
    body: str


class MediaMessageRequest(BaseModel):
    recipient_phone: str
    data: str        # base64
    mimetype: str
    caption: str = ""


# ── Session endpoints ──────────────────────────────────────────────

@app.get("/sessions")
async def list_sessions(
    x_bridge_key: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    _check_key(x_bridge_key)
    return list(_sessions.values())


@app.post("/sessions", status_code=200)
async def create_session(
    body: CreateSessionRequest,
    x_bridge_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_key(x_bridge_key)
    if body.session_id not in _sessions:
        _sessions[body.session_id] = {
            "session_id": body.session_id,
            "connected_phone": body.connected_phone,
            "status": "connected",
        }
        logger.info("Session registered: %s (phone=%s)", body.session_id, body.connected_phone)
    return _sessions[body.session_id]


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str = Path(...),
    x_bridge_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_key(x_bridge_key)
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return _sessions[session_id]


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str = Path(...),
    x_bridge_key: str | None = Header(default=None),
) -> Response:
    _check_key(x_bridge_key)
    _sessions.pop(session_id, None)
    return Response(status_code=204)


# ── Outbound message endpoints (called by Gateway) ─────────────────

@app.post("/sessions/{session_id}/messages/text")
async def receive_text(
    session_id: str = Path(...),
    body: TextMessageRequest = ...,
    x_bridge_key: str | None = Header(default=None),
) -> dict[str, str]:
    _check_key(x_bridge_key)
    provider_message_id = uuid4().hex
    logger.info(
        "REPLY [%s → %s]: %s",
        session_id, body.recipient_phone, body.body[:80],
    )
    await get_reply_queue(body.recipient_phone).put(body.body)
    return {"provider_message_id": provider_message_id}


@app.post("/sessions/{session_id}/messages/media")
async def receive_media(
    session_id: str = Path(...),
    body: MediaMessageRequest = ...,
    x_bridge_key: str | None = Header(default=None),
) -> dict[str, str]:
    _check_key(x_bridge_key)
    provider_message_id = uuid4().hex
    caption = body.caption or "(media)"
    logger.info(
        "MEDIA REPLY [%s → %s]: %s (%s)",
        session_id, body.recipient_phone, body.mimetype, caption[:40],
    )
    await get_reply_queue(body.recipient_phone).put(f"[media: {body.mimetype}] {caption}".strip())
    return {"provider_message_id": provider_message_id}


# ── Convenience: register a session without auth (called by main.py startup) ──

def register_session(session_id: str, connected_phone: str = "") -> None:
    """Register a session directly (no HTTP call needed at startup)."""
    _sessions[session_id] = {
        "session_id": session_id,
        "connected_phone": connected_phone,
        "status": "connected",
    }
    logger.info("Session pre-registered: %s (phone=%s)", session_id, connected_phone)
