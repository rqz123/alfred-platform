"""
Dispatch service: routes inbound WhatsApp messages to the appropriate
micro-service and sends the reply back to the user.

Standard flow (no pending session):
  message → detect_intent → find_service → POST /alfred/execute → reply
  If response is INSUFFICIENT_DATA → save PendingSession, forward prompt.

Multi-turn follow-up flow:
  next message + pending session exists:
    - cancel keyword  → clear pending, send "Cancelled" reply
    - new intent      → clear pending, handle as fresh request
    - no new intent   → extract entities, merge, retry the service call
                        (up to MAX_RETRIES times, then give up)
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlmodel import Session

from app.core.config import get_settings
from app.models.chat import Contact, Conversation, Message, WhatsAppConnection
from app.schemas.chat import MessageRead
from app.services.bridge_service import send_text_via_bridge
from app.services.intent_service import detect_intent, extract_entities, is_affirmative
from app.services.pending_sessions import (
    MAX_RETRIES,
    PendingSession,
    clear as clear_pending,
    get as get_pending,
    is_cancel,
    save as save_pending,
)
from app.services.service_registry import ServiceRegistry

logger = logging.getLogger('alfred.dispatch')

# Module-level singleton — loaded once at startup
_registry = ServiceRegistry()


# ──────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────

def dispatch_message(session: Session, msg: MessageRead) -> None:
    """
    Route msg to a downstream service and reply to the sender.
    Silently returns on any non-fatal error so the webhook always gets 200.
    """
    settings = get_settings()
    if not settings.dispatch_enabled:
        return

    # Resolve contact early — needed for all paths
    conv = session.get(Conversation, msg.conversation_id)
    if conv is None:
        logger.error('Conversation %s not found', msg.conversation_id)
        return
    contact = session.get(Contact, conv.contact_id)
    if contact is None:
        return
    phone = contact.phone_number

    # ── Image message → receipt processing (no text required) ─────
    if msg.message_type == "image" and msg.media_url:
        _handle_image(session, conv, phone, msg, settings)
        return

    text = msg.transcript or msg.body
    if not text or not text.strip():
        return

    pending = get_pending(phone)

    # ── Cancel? (only when a pending session exists) ───────────────
    if is_cancel(text) and pending:
        clear_pending(phone)
        _reply(session, conv, phone, 'Cancelled. Anything else I can help with?', settings)
        return

    # ── Follow-up message (pending session exists) ─────────────────
    if pending:
        result = detect_intent(text)

        if result is not None:
            # User switched to a new intent — abandon the old pending
            logger.debug('New intent %s while pending %s for %s; dropping old pending',
                         result['intent'], pending.intent, phone)
            clear_pending(phone)
            _handle_fresh(session, conv, phone, msg, result, settings)
        else:
            _handle_followup(session, conv, phone, msg, pending, text, settings)
        return

    # ── Fresh request ─────────────────────────────────────────────
    result = detect_intent(text)
    if result is None:
        # Short messages (≤ 20 chars) might be affirmative responses in any language.
        # Ask the LLM before falling through to chat, so "Ok", "好", "yes", etc.
        # reliably acknowledge a waiting reminder regardless of phrasing.
        if len(text.strip()) <= 20 and is_affirmative(text):
            result = {'intent': 'acknowledge_reminder', 'entities': {}}
            _handle_fresh(session, conv, phone, msg, result, settings)
            return
        from app.services.chat_service import llm_chat_reply
        _reply(session, conv, phone, llm_chat_reply(session, msg, settings), settings)
        return
    _handle_fresh(session, conv, phone, msg, result, settings)


# ──────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────

def _handle_image(
    session: Session,
    conv: Conversation,
    phone: str,
    msg: MessageRead,
    settings,
) -> None:
    """Read a locally-stored image and forward it to OurCents for receipt processing."""
    import base64
    from app.services.media_service import get_media_path

    # media_url is a local API path like /api/media/<filename>
    filename = (msg.media_url or "").rsplit("/", 1)[-1]
    path = get_media_path(filename) if filename else None
    if not path or not path.exists():
        logger.error('Image file not found for media_url=%s', msg.media_url)
        _reply(session, conv, phone,
               "I couldn't read the image. Please try again.", settings)
        return

    try:
        content = path.read_bytes()
    except Exception as exc:
        logger.error('Image read failed for %s: %s', path, exc)
        _reply(session, conv, phone,
               "I couldn't read the image. Please try again.", settings)
        return

    media = {
        'content': content,
        'content_type': 'image/jpeg',
        'filename': filename,
    }

    service = _registry.find_service('process_receipt_image')
    if service is None:
        logger.warning('No service registered for process_receipt_image')
        return

    image_b64 = base64.b64encode(media['content']).decode()
    entities = {
        'image_data': image_b64,
        'mime_type': media.get('content_type', 'image/jpeg'),
        'filename': media.get('filename', 'receipt.jpg'),
        'caption': msg.body,  # user's caption text, if any
    }

    # Image processing (AI OCR) can take longer — use 60s timeout
    resp = _call_service(service, phone, msg.conversation_id,
                         'process_receipt_image', entities, timeout=60.0)
    if resp is None:
        _reply(session, conv, phone,
               "Receipt processing failed. Please try again.", settings)
        return

    _reply_from_resp(session, conv, phone, resp, settings)


def _handle_fresh(
    session: Session,
    conv: Conversation,
    phone: str,
    msg: MessageRead,
    result: dict,
    settings,
) -> None:
    """Route a freshly-detected intent to the appropriate service."""
    intent: str = result['intent']
    entities: dict = result['entities']

    service = _registry.find_service(intent)
    if service is None:
        logger.warning('No service registered for intent %s', intent)
        _reply(session, conv, phone,
               "I understood your request but that feature isn't available right now. Please try again later.",
               settings)
        return

    resp = _call_service(service, phone, msg.conversation_id, intent, entities)
    if resp is None:
        return

    if resp.get('error_code') == 'INSUFFICIENT_DATA':
        save_pending(phone, intent, entities, service)

    _reply_from_resp(session, conv, phone, resp, settings)


def _handle_followup(
    session: Session,
    conv: Conversation,
    phone: str,
    msg: MessageRead,
    pending: PendingSession,
    text: str,
    settings,
) -> None:
    """Merge new entities from the follow-up message and retry the service."""
    new_entities = extract_entities(text, pending.intent)
    merged = {**pending.entities, **new_entities}

    pending.retries += 1
    if pending.retries > MAX_RETRIES:
        clear_pending(phone)
        _reply(session, conv, phone,
               "I'm having trouble understanding. Let's start over — what would you like to do?",
               settings)
        return

    if not new_entities:
        logger.debug('Follow-up from %s yielded no entities for intent %s; re-prompting',
                     phone, pending.intent)

    resp = _call_service(pending.service, phone, msg.conversation_id, pending.intent, merged)
    if resp is None:
        return

    if resp.get('error_code') == 'INSUFFICIENT_DATA':
        # Update stored entities in-place so retries counter is preserved
        pending.entities = merged
    else:
        clear_pending(phone)

    _reply_from_resp(session, conv, phone, resp, settings)


def _call_service(
    service: dict,
    phone: str,
    conversation_id: str,
    intent: str,
    entities: dict,
    timeout: float = 15.0,
) -> dict | None:
    """POST to /alfred/execute and return the parsed JSON, or None on error."""
    payload = {
        'request_id': str(uuid4()),
        'user_id': phone,
        'whatsapp_id': phone,
        'intent': intent,
        'entities': entities,
        'session': {'conversation_id': conversation_id},
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = httpx.post(
            f"{service['url']}/alfred/execute",
            json=payload,
            headers={'X-Alfred-API-Key': service['api_key']},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error('Dispatch to %s failed: %s', service['name'], exc)
        return None


def _reply_from_resp(
    session: Session,
    conv: Conversation,
    phone: str,
    resp: dict,
    settings,
) -> None:
    """Format and send the service response back to the WhatsApp user."""
    text: str = resp.get('message', '')
    if not text:
        return
    if quick := resp.get('quick_replies'):
        text += '\n\n' + '  '.join(f'[{q}]' for q in quick)
    _reply(session, conv, phone, text, settings)


def _reply(
    session: Session,
    conv: Conversation,
    phone: str,
    text: str,
    settings,
) -> None:
    """Send plain text back to the user via bridge or Cloud API, and persist it."""
    provider_message_id: str | None = None
    if settings.whatsapp_mode == 'bridge' and conv.connection_id:
        conn = session.get(WhatsAppConnection, conv.connection_id)
        if conn:
            try:
                provider_message_id = send_text_via_bridge(conn.bridge_session_id, phone, text)
            except Exception as exc:
                logger.error('Bridge reply failed for %s: %s', phone, exc)
    else:
        _send_cloud_reply(phone, text, settings)

    # Persist the outbound reply in the conversation so it appears in the UI.
    try:
        from datetime import datetime, timezone
        msg = Message(
            conversation_id=conv.id,
            provider_message_id=provider_message_id,
            direction='outbound',
            message_type='text',
            body=text,
            delivery_status='sent' if provider_message_id else 'queued',
        )
        session.add(msg)
        conv.updated_at = datetime.now(timezone.utc)
        session.add(conv)
        session.commit()
    except Exception as exc:
        logger.warning('Failed to persist outbound reply: %s', exc)


def _send_cloud_reply(recipient_phone: str, body: str, settings) -> None:
    """Send a plain text reply via WhatsApp Cloud API."""
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        logger.warning('Cloud reply skipped — WhatsApp credentials not configured')
        return
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    try:
        httpx.post(
            url,
            json={
                'messaging_product': 'whatsapp',
                'recipient_type': 'individual',
                'to': recipient_phone,
                'type': 'text',
                'text': {'preview_url': False, 'body': body},
            },
            headers={
                'Authorization': f'Bearer {settings.whatsapp_access_token}',
                'Content-Type': 'application/json',
            },
            timeout=15.0,
        )
    except Exception as exc:
        logger.error('Cloud reply failed for %s: %s', recipient_phone, exc)
