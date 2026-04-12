import hashlib
import hmac
from mimetypes import guess_extension

import httpx
from fastapi import HTTPException, status
from sqlmodel import Session

from app.core.config import get_settings
from app.repositories.chat_repository import (
    assign_provider_message_id,
    create_inbound_message,
    create_or_get_contact,
    get_or_create_conversation,
    update_message_delivery_status,
)
from app.schemas.chat import MessageRead
from app.services.stt_service import transcribe_audio_bytes
from app.services.tts_service import synthesize_speech


def verify_webhook_request(body: bytes, signature: str | None) -> None:
    settings = get_settings()
    if not settings.whatsapp_app_secret:
        return
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing webhook signature")

    expected = hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    provided = signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature")


def process_webhook_payload(session: Session, payload: dict) -> None:
    entries = payload.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts_by_wa_id = {
                item.get("wa_id"): item.get("profile", {}).get("name")
                for item in value.get("contacts", [])
                if item.get("wa_id")
            }

            for message in value.get("messages", []):
                _persist_inbound_message(session, message, contacts_by_wa_id)

            for status_item in value.get("statuses", []):
                provider_message_id = status_item.get("id")
                status_value = status_item.get("status")
                if provider_message_id and status_value:
                    update_message_delivery_status(session, provider_message_id, status_value)


def send_text_message(session: Session, message_id: int, recipient_phone: str, body: str) -> MessageRead:
    url = _messages_url()
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    response = _graph_post(url, json=payload)

    data = response.json()
    provider_message_id = data.get("messages", [{}])[0].get("id")
    if not provider_message_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WhatsApp delivery response did not include a message id",
        )

    return assign_provider_message_id(session, message_id, provider_message_id, "sent")


def send_voice_message(session: Session, message_id: int, recipient_phone: str, text: str) -> MessageRead:
    speech = synthesize_speech(text)
    media_id = upload_media_bytes(speech.filename, speech.audio_bytes, speech.content_type)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
        "type": "audio",
        "audio": {"id": media_id},
    }
    response = _graph_post(_messages_url(), json=payload)
    data = response.json()
    provider_message_id = data.get("messages", [{}])[0].get("id")
    if not provider_message_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WhatsApp audio delivery response did not include a message id",
        )

    return assign_provider_message_id(session, message_id, provider_message_id, "sent")


def upload_media_bytes(filename: str, content: bytes, content_type: str) -> str:
    settings = get_settings()
    _ensure_whatsapp_configured()
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}/media"
    )
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
    }
    files = {
        "file": (filename, content, content_type),
        "type": (None, content_type),
        "messaging_product": (None, "whatsapp"),
    }

    try:
        response = httpx.post(url, files=files, headers=headers, timeout=60.0)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WhatsApp media upload failed: {exc}",
        ) from exc

    if response.is_error:
        detail = response.text or "WhatsApp media upload failed"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

    media_id = response.json().get("id")
    if not media_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WhatsApp media upload response did not include a media id",
        )
    return media_id


def _persist_inbound_message(
    session: Session,
    message: dict,
    contacts_by_wa_id: dict[str, str | None],
) -> None:
    sender_phone = message.get("from")
    if not sender_phone:
        return

    display_name = contacts_by_wa_id.get(sender_phone)
    contact = create_or_get_contact(session, sender_phone, display_name)
    conversation = get_or_create_conversation(session, contact)
    message_type = message.get("type", "text")
    provider_message_id = message.get("id")
    body, media_url = _extract_message_content(message)
    transcript = None
    if message_type == "audio" and media_url:
        transcript = _transcribe_audio_reference(media_url)
    create_inbound_message(
        session,
        conversation,
        provider_message_id=provider_message_id,
        message_type=message_type,
        body=body,
        media_url=media_url,
        transcript=transcript,
    )


def _extract_message_content(message: dict) -> tuple[str | None, str | None]:
    message_type = message.get("type", "text")
    if message_type == "text":
        return message.get("text", {}).get("body"), None
    if message_type == "image":
        image = message.get("image", {})
        caption = image.get("caption")
        media_ref = image.get("id")
        return caption, media_ref
    if message_type == "audio":
        audio = message.get("audio", {})
        media_ref = audio.get("id")
        return None, media_ref
    if message_type == "document":
        document = message.get("document", {})
        filename = document.get("filename")
        media_ref = document.get("id")
        return filename, media_ref
    return None, None


def _transcribe_audio_reference(media_id: str) -> str | None:
    try:
        media = download_media_bytes(media_id)
        return transcribe_audio_bytes(media["content"], media["filename"], media["content_type"])
    except HTTPException:
        return None


def download_media_bytes(media_id: str) -> dict[str, bytes | str]:
    metadata = _graph_get(_media_url(media_id)).json()
    download_url = metadata.get("url")
    content_type = metadata.get("mime_type", "application/octet-stream")
    if not download_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WhatsApp media metadata did not include a download URL",
        )

    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
    }

    try:
        response = httpx.get(download_url, headers=headers, timeout=60.0)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WhatsApp media download failed: {exc}",
        ) from exc

    if response.is_error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=response.text or "WhatsApp media download failed",
        )

    extension = guess_extension(content_type) or ".bin"
    return {
        "content": response.content,
        "content_type": content_type,
        "filename": f"{media_id}{extension}",
    }


def _graph_get(url: str) -> httpx.Response:
    settings = get_settings()
    _ensure_whatsapp_configured()
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
    }
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WhatsApp request failed: {exc}",
        ) from exc

    if response.is_error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=response.text or "WhatsApp request failed",
        )
    return response


def _graph_post(url: str, json: dict | None = None) -> httpx.Response:
    settings = get_settings()
    _ensure_whatsapp_configured()
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(url, json=json, headers=headers, timeout=30.0)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WhatsApp delivery failed: {exc}",
        ) from exc

    if response.is_error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=response.text or "WhatsApp delivery failed",
        )
    return response


def _messages_url() -> str:
    settings = get_settings()
    _ensure_whatsapp_configured()
    return (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )


def _media_url(media_id: str) -> str:
    settings = get_settings()
    _ensure_whatsapp_configured()
    return f"https://graph.facebook.com/{settings.whatsapp_api_version}/{media_id}"


def _ensure_whatsapp_configured() -> None:
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp outbound delivery is not configured",
        )