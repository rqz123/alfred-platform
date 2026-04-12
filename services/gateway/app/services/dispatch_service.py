"""
Dispatch service: routes inbound WhatsApp messages to the appropriate
micro-service and sends the reply back to the user.

Flow:
  MessageRead → detect_intent → find_service → POST /alfred/execute → reply
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlmodel import Session

from app.core.config import get_settings
from app.models.chat import Contact, Conversation, WhatsAppConnection
from app.schemas.chat import MessageRead
from app.services.bridge_service import send_text_via_bridge
from app.services.intent_service import detect_intent
from app.services.service_registry import ServiceRegistry

logger = logging.getLogger('alfred.dispatch')

# Module-level singleton — loaded once at startup
_registry = ServiceRegistry()


def dispatch_message(session: Session, msg: MessageRead) -> None:
    """
    Attempt to route msg to a downstream service and reply to the sender.
    Silently returns on any non-fatal error so the webhook always gets 200.
    """
    settings = get_settings()
    if not settings.dispatch_enabled:
        return

    # 1. Get text (prefer STT transcript for audio)
    text = msg.transcript or msg.body
    if not text or not text.strip():
        return

    # 2. Detect intent
    result = detect_intent(text)
    if result is None:
        return
    intent: str = result['intent']
    entities: dict = result['entities']

    # 3. Find target service
    service = _registry.find_service(intent)
    if service is None:
        logger.debug('No service registered for intent %s', intent)
        return

    # 4. Look up conversation + contact
    conv = session.get(Conversation, msg.conversation_id)
    if conv is None:
        logger.error('Conversation %s not found for dispatch', msg.conversation_id)
        return
    contact = session.get(Contact, conv.contact_id)
    if contact is None:
        return
    phone = contact.phone_number

    # 5. Call ASI /alfred/execute
    payload = {
        'request_id': str(uuid4()),
        'user_id': phone,
        'whatsapp_id': phone,
        'intent': intent,
        'entities': entities,
        'session': {'conversation_id': msg.conversation_id},
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = httpx.post(
            f"{service['url']}/alfred/execute",
            json=payload,
            headers={'X-Alfred-API-Key': service['api_key']},
            timeout=15.0,
        )
        r.raise_for_status()
        resp = r.json()
    except Exception as exc:
        logger.error('Dispatch to %s failed: %s', service['name'], exc)
        return

    # 6. Build reply text
    reply_text: str = resp.get('message', '')
    if not reply_text:
        return
    if quick := resp.get('quick_replies'):
        reply_text += '\n\n' + '  '.join(f'[{q}]' for q in quick)

    # 7. Send reply
    if settings.whatsapp_mode == 'bridge' and conv.connection_id:
        conn = session.get(WhatsAppConnection, conv.connection_id)
        if conn:
            try:
                send_text_via_bridge(conn.bridge_session_id, phone, reply_text)
            except Exception as exc:
                logger.error('Bridge reply failed for %s: %s', phone, exc)
    else:
        # Cloud API mode: send directly via Graph API
        _send_cloud_reply(phone, reply_text)


def _send_cloud_reply(recipient_phone: str, body: str) -> None:
    """Send a plain text reply via WhatsApp Cloud API without DB tracking."""
    settings = get_settings()
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
