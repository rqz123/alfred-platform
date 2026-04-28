"""
Send inbound messages to the Gateway as if from the Bridge.

The Gateway's /internal/bridge/messages endpoint expects:
  POST /internal/bridge/messages
  X-Bridge-Key: <key>
  {
    "session_id": str,
    "provider_message_id": str,   # 32-char hex
    "sender_phone": str,
    "sender_name": str | null,
    "message_type": "text",
    "body": str
  }
"""

from uuid import uuid4

import httpx

from . import settings


async def send_message(
    phone: str,
    name: str,
    body: str,
    session_id: str | None = None,
) -> str:
    """
    Post a message to the Gateway webhook on behalf of a virtual phone.
    Returns the provider_message_id that was sent.
    """
    sid = session_id or settings.SESSION_ID
    msg_id = uuid4().hex  # 32-char hex, matching real Bridge format

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.GATEWAY_URL}/api/internal/bridge/messages",
            headers={"X-Bridge-Key": settings.BRIDGE_API_KEY},
            json={
                "session_id": sid,
                "provider_message_id": msg_id,
                "sender_phone": phone,
                "sender_name": name,
                "message_type": "text",
                "body": body,
            },
        )
        resp.raise_for_status()

    return msg_id


async def check_gateway_health() -> bool:
    """Return True if the Gateway is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.GATEWAY_URL}/healthz")
            return resp.status_code < 500
    except Exception:
        return False
