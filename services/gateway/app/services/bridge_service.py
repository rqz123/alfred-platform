import logging

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings


logger = logging.getLogger("alfred.bridge")


def _headers() -> dict[str, str]:
    return {"X-Bridge-Key": get_settings().bridge_api_key}


def _url(path: str) -> str:
    return f"{get_settings().bridge_api_url}{path}"


def _normalize(data: dict) -> dict:
    return {
        "id": data.get("id"),
        "status": data.get("status", "unknown"),
        "qr_code_data_url": data.get("qr_code_data_url"),
        "connected_phone": data.get("connected_phone"),
        "connected_name": data.get("connected_name"),
        "last_error": data.get("last_error"),
    }


def list_bridge_sessions() -> list[dict]:
    try:
        response = httpx.get(_url("/sessions"), headers=_headers(), timeout=10.0)
    except httpx.HTTPError as exc:
        logger.error("Bridge sessions request failed: %s", exc)
        return []
    if response.is_error:
        logger.error("Bridge sessions error: %s", response.text)
        return []
    return [_normalize(s) for s in response.json()]


def create_bridge_session(session_id: str) -> dict:
    try:
        response = httpx.post(
            _url("/sessions"),
            json={"session_id": session_id},
            headers=_headers(),
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Bridge error: {exc}") from exc
    if response.is_error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=response.text or "Bridge error")
    return _normalize(response.json())


def get_bridge_session(session_id: str) -> dict | None:
    try:
        response = httpx.get(_url(f"/sessions/{session_id}"), headers=_headers(), timeout=10.0)
    except httpx.HTTPError:
        return None
    if response.is_error:
        return None
    return _normalize(response.json())


def delete_bridge_session(session_id: str) -> None:
    try:
        httpx.delete(_url(f"/sessions/{session_id}"), headers=_headers(), timeout=15.0)
    except httpx.HTTPError as exc:
        logger.warning("Bridge delete session failed for %s: %s", session_id, exc)


def send_text_via_bridge(session_id: str, recipient_phone: str, body: str) -> str:
    logger.info("Sending text via bridge session=%s to %s", session_id, recipient_phone)
    try:
        response = httpx.post(
            _url(f"/sessions/{session_id}/messages/text"),
            json={"recipient_phone": recipient_phone, "body": body},
            headers=_headers(),
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Bridge send failed: {exc}") from exc
    if response.is_error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=response.text or "Bridge send failed")
    provider_message_id = response.json().get("provider_message_id")
    if not provider_message_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Bridge response missing message id")
    logger.info("Bridge send succeeded session=%s provider_message_id=%s", session_id, provider_message_id)
    return provider_message_id


def send_image_via_bridge(session_id: str, recipient_phone: str, data_b64: str, mimetype: str, caption: str | None) -> str:
    logger.info("Sending image via bridge session=%s to %s", session_id, recipient_phone)
    try:
        response = httpx.post(
            _url(f"/sessions/{session_id}/messages/media"),
            json={"recipient_phone": recipient_phone, "data": data_b64, "mimetype": mimetype, "caption": caption or ""},
            headers=_headers(),
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Bridge send failed: {exc}") from exc
    if response.is_error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=response.text or "Bridge send failed")
    provider_message_id = response.json().get("provider_message_id")
    if not provider_message_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Bridge response missing message id")
    logger.info("Bridge image send succeeded session=%s provider_message_id=%s", session_id, provider_message_id)
    return provider_message_id


def normalize_phone_number(phone_number: str) -> str:
    normalized = "".join(c for c in phone_number if c.isdigit())
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A valid phone number is required")
    return normalized


