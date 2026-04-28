import base64
import logging
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.models.chat import Contact
from app.repositories.auth_repository import get_admin_user
from app.repositories.chat_repository import (
    assign_provider_message_id,
    clear_conversation_messages,
    delete_conversation,
    delete_all_conversations,
    create_or_get_conversation_for_contact,
    create_outbound_message,
    create_outbound_message_for_contact,
    create_inbound_message_for_contact,
    get_conversation_or_404,
    list_conversation_messages,
    list_conversations,
    mark_conversation_read,
    update_message_delivery_status,
    update_message_status_by_id,
)
from app.repositories.connection_repository import (
    create_connection_record,
    delete_connection_record,
    get_connection_by_id,
    get_or_create_connection_by_session_id,
    list_connections,
)
from app.schemas.auth import LoginResponse, TokenPayload
from app.schemas.bridge import BridgeAck, BridgeInboundMessage, BridgeOutboundMessage
from app.schemas.chat import ConversationCreate, ConversationRead, MessageCreate, MessageRead
from app.schemas.connection import ConnectionCreate, ConnectionRead
from app.services.auth_service import build_login_response, get_current_admin
from app.services.bridge_service import (
    create_bridge_session,
    delete_bridge_session,
    get_bridge_session,
    list_bridge_sessions,
    normalize_phone_number,
    send_image_via_bridge,
    send_text_via_bridge,
)
from app.services.dispatch_service import dispatch_message
from app.services.whatsapp_service import send_text_message, send_voice_message
from app.services.media_service import get_media_path, save_base64_media, save_uploaded_media


auth_router = APIRouter(tags=["auth"])
conversation_router = APIRouter(tags=["conversations"])
message_router = APIRouter(tags=["messages"])
connection_router = APIRouter(tags=["connection"])
internal_router = APIRouter(tags=["internal"])
logger = logging.getLogger("alfred.api")


@auth_router.post("/auth/login", response_model=LoginResponse)
def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> LoginResponse:
    logger.info("Admin login attempt for user=%s", form_data.username)
    admin = get_admin_user(session, form_data.username)
    if admin is None:
        logger.warning("Admin login failed for user=%s", form_data.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    logger.info("Admin login succeeded for user=%s", form_data.username)
    return build_login_response(response, admin, form_data.password)


@auth_router.get("/auth/me", response_model=TokenPayload)
def me(admin: TokenPayload = Depends(get_current_admin)) -> TokenPayload:
    return admin


@conversation_router.get("/conversations", response_model=list[ConversationRead])
def get_conversations(
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> list[ConversationRead]:
    return list_conversations(session)


@conversation_router.post("/conversations", response_model=ConversationRead)
def create_conversation(
    payload: ConversationCreate,
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> ConversationRead:
    normalized_phone = normalize_phone_number(payload.phone_number)
    logger.info("Creating proactive conversation for phone=%s", normalized_phone)
    connection_id = payload.connection_id
    if connection_id is None:
        db_connections = list_connections(session)
        live = {s["id"]: s for s in list_bridge_sessions()}
        for conn in db_connections:
            if live.get(conn.bridge_session_id, {}).get("status") == "connected":
                connection_id = conn.id
                break
    return create_or_get_conversation_for_contact(
        session,
        ConversationCreate(
            phone_number=normalized_phone,
            contact_name=payload.contact_name,
            first_message=payload.first_message,
            connection_id=connection_id,
        ),
    )


@connection_router.get("/connections", response_model=list[ConnectionRead])
def list_connections_endpoint(
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> list[ConnectionRead]:
    db_connections = list_connections(session)
    live = {s["id"]: s for s in list_bridge_sessions()}
    result: list[ConnectionRead] = []
    for conn in db_connections:
        live_s = live.get(conn.bridge_session_id, {})
        result.append(ConnectionRead(
            id=conn.id,
            bridge_session_id=conn.bridge_session_id,
            label=conn.label,
            created_at=conn.created_at,
            status=live_s.get("status", "offline"),
            qr_code_data_url=live_s.get("qr_code_data_url"),
            connected_phone=live_s.get("connected_phone"),
            connected_name=live_s.get("connected_name"),
            last_error=live_s.get("last_error"),
        ))
    return result


@connection_router.post("/connections", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
def create_connection_endpoint(
    payload: ConnectionCreate,
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> ConnectionRead:
    session_id = payload.session_id or str(uuid4())
    db_connection = create_connection_record(session, session_id, payload.label)
    try:
        bridge_session = create_bridge_session(session_id)
    except HTTPException:
        delete_connection_record(session, db_connection.id)
        raise
    logger.info("Created WhatsApp connection session_id=%s", session_id)
    return ConnectionRead(
        id=db_connection.id,
        bridge_session_id=db_connection.bridge_session_id,
        label=db_connection.label,
        created_at=db_connection.created_at,
        status=bridge_session.get("status", "starting"),
        qr_code_data_url=bridge_session.get("qr_code_data_url"),
        connected_phone=bridge_session.get("connected_phone"),
        connected_name=bridge_session.get("connected_name"),
        last_error=bridge_session.get("last_error"),
    )


@connection_router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection_endpoint(
    connection_id: int,
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> Response:
    conn = get_connection_by_id(session, connection_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    delete_bridge_session(conn.bridge_session_id)
    delete_connection_record(session, connection_id)
    logger.info("Deleted WhatsApp connection id=%s session_id=%s", connection_id, conn.bridge_session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@message_router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
def get_messages(
    conversation_id: int,
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> list[MessageRead]:
    get_conversation_or_404(session, conversation_id)
    mark_conversation_read(session, conversation_id)
    return list_conversation_messages(session, conversation_id)


@message_router.post("/conversations/{conversation_id}/messages", response_model=MessageRead)
def send_message(
    conversation_id: int,
    payload: MessageCreate,
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> MessageRead:
    conversation = get_conversation_or_404(session, conversation_id)
    contact = session.get(Contact, conversation.contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    message = create_outbound_message(session, conversation, payload)
    logger.info(
        "Outbound message queued: conversation_id=%s contact=%s type=%s send_as_voice=%s",
        conversation_id,
        contact.phone_number,
        payload.message_type,
        payload.send_as_voice,
    )
    if not payload.body:
        return message

    try:
        settings = get_settings()
        if settings.whatsapp_mode == "bridge":
            bridge_session_id: str | None = None
            if conversation.connection_id is not None:
                conn = get_connection_by_id(session, conversation.connection_id)
                if conn is None:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="WhatsApp connection not found")
                live = get_bridge_session(conn.bridge_session_id)
                if not live or live.get("status") != "connected":
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="WhatsApp session is not connected")
                bridge_session_id = conn.bridge_session_id
            else:
                all_sessions = list_bridge_sessions()
                connected = [s for s in all_sessions if s.get("status") == "connected"]
                if not connected:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No connected WhatsApp session")
                bridge_session_id = connected[0]["id"]

            if payload.send_as_voice:
                logger.warning("Bridge voice reply requested but not implemented")
                raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Voice replies not implemented in bridge mode")
            if payload.message_type != "text":
                return message
            provider_message_id = send_text_via_bridge(bridge_session_id, contact.phone_number, payload.body)
            logger.info(
                "Bridge outbound sent: conversation_id=%s contact=%s provider_message_id=%s",
                conversation_id,
                contact.phone_number,
                provider_message_id,
            )
            return assign_provider_message_id(session, message.id, provider_message_id, "sent")
        if payload.send_as_voice:
            return send_voice_message(session, message.id, contact.phone_number, payload.body)
        if payload.message_type == "text":
            return send_text_message(session, message.id, contact.phone_number, payload.body)
        return message
    except HTTPException as exc:
        update_message_status_by_id(session, message.id, "failed")
        logger.error(
            "Outbound message failed: conversation_id=%s contact=%s detail=%s",
            conversation_id,
            contact.phone_number,
            exc.detail,
        )
        raise


@message_router.post("/conversations/{conversation_id}/messages/media", response_model=MessageRead)
def send_media_message(
    conversation_id: int,
    file: UploadFile,
    caption: str | None = Form(default=None),
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> MessageRead:
    conversation = get_conversation_or_404(session, conversation_id)
    contact = session.get(Contact, conversation.contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image files are supported")

    raw = file.file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image too large (max 10 MB)")

    media_url = save_uploaded_media(raw, file.content_type)
    data_b64 = base64.b64encode(raw).decode()

    payload = MessageCreate(message_type="image", body=caption, media_url=media_url)
    message = create_outbound_message(session, conversation, payload)
    logger.info("Outbound image queued: conversation_id=%s contact=%s", conversation_id, contact.phone_number)

    settings = get_settings()
    if settings.whatsapp_mode != "bridge":
        return message

    try:
        bridge_session_id: str | None = None
        if conversation.connection_id is not None:
            conn = get_connection_by_id(session, conversation.connection_id)
            if conn is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="WhatsApp connection not found")
            live = get_bridge_session(conn.bridge_session_id)
            if not live or live.get("status") != "connected":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="WhatsApp session is not connected")
            bridge_session_id = conn.bridge_session_id
        else:
            all_sessions = list_bridge_sessions()
            connected = [s for s in all_sessions if s.get("status") == "connected"]
            if not connected:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No connected WhatsApp session")
            bridge_session_id = connected[0]["id"]

        provider_message_id = send_image_via_bridge(
            bridge_session_id, contact.phone_number, data_b64, file.content_type, caption
        )
        logger.info("Bridge image sent: conversation_id=%s provider_message_id=%s", conversation_id, provider_message_id)
        return assign_provider_message_id(session, message.id, provider_message_id, "sent")
    except HTTPException as exc:
        update_message_status_by_id(session, message.id, "failed")
        logger.error("Outbound image failed: conversation_id=%s detail=%s", conversation_id, exc.detail)
        raise


@message_router.delete("/conversations/{conversation_id}/messages", status_code=status.HTTP_204_NO_CONTENT)
def clear_messages(
    conversation_id: int,
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> Response:
    conversation = get_conversation_or_404(session, conversation_id)
    clear_conversation_messages(session, conversation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@conversation_router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation_endpoint(
    conversation_id: int,
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> Response:
    conversation = get_conversation_or_404(session, conversation_id)
    delete_conversation(session, conversation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@conversation_router.delete("/conversations", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_conversations_endpoint(
    _: TokenPayload = Depends(get_current_admin),
    session: Session = Depends(get_session),
) -> Response:
    delete_all_conversations(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@internal_router.post("/internal/bridge/messages", status_code=status.HTTP_204_NO_CONTENT)
def receive_bridge_message(
    payload: BridgeInboundMessage,
    x_bridge_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Response:
    settings = get_settings()
    if x_bridge_key != settings.bridge_api_key:
        logger.warning("Rejected inbound bridge message due to invalid bridge key")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bridge key")

    # Skip messages where Alfred's own WhatsApp number is the sender — these
    # are self-messages (e.g. the phone receiving its own sent notification)
    # and should never create a contact or trigger a dispatch.
    try:
        bridge_sessions = list_bridge_sessions()
        alfred_phone = next(
            (s.get("connected_phone") for s in bridge_sessions if s.get("id") == payload.session_id),
            None,
        )
        if alfred_phone and payload.sender_phone == alfred_phone:
            logger.debug("Skipping self-message from Alfred's own number %s", alfred_phone)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception:
        pass  # if bridge is unreachable, process the message anyway

    logger.info(
        "Inbound bridge message received: session=%s sender=%s type=%s provider_message_id=%s",
        payload.session_id,
        payload.sender_phone,
        payload.message_type,
        payload.provider_message_id,
    )
    connection = get_or_create_connection_by_session_id(session, payload.session_id)
    stored_media_url = payload.media_url
    transcript = payload.transcript
    if stored_media_url and stored_media_url.startswith("data:"):
        mimetype = stored_media_url.split(";")[0].removeprefix("data:")
        data_b64 = stored_media_url.split(",", 1)[1]
        stored_media_url = save_base64_media(data_b64, mimetype)
        # Run STT on inbound voice messages
        if payload.message_type in ("ptt", "audio") and not transcript:
            try:
                import base64
                from app.services.stt_service import transcribe_audio_bytes
                audio_bytes = base64.b64decode(data_b64)
                ext = stored_media_url.rsplit(".", 1)[-1] if stored_media_url else "ogg"
                transcript = transcribe_audio_bytes(audio_bytes, f"voice.{ext}", mimetype)
                logger.info("STT transcript for %s: %s", payload.sender_phone, transcript)
            except Exception as exc:
                logger.warning("STT failed for %s: %s", payload.sender_phone, exc)
    stored = create_inbound_message_for_contact(
        session,
        phone_number=payload.sender_phone,
        display_name=payload.sender_name,
        provider_message_id=payload.provider_message_id,
        message_type=payload.message_type,
        body=payload.body,
        media_url=stored_media_url,
        transcript=transcript,
        connection_id=connection.id,
    )
    if stored:
        dispatch_message(session, stored)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@internal_router.post("/internal/bridge/outbound", status_code=status.HTTP_204_NO_CONTENT)
def receive_bridge_outbound_message(
    payload: BridgeOutboundMessage,
    x_bridge_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Response:
    settings = get_settings()
    if x_bridge_key != settings.bridge_api_key:
        logger.warning("Rejected outbound bridge sync due to invalid bridge key")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bridge key")

    logger.info(
        "Outbound bridge message synced: session=%s recipient=%s type=%s provider_message_id=%s",
        payload.session_id,
        payload.recipient_phone,
        payload.message_type,
        payload.provider_message_id,
    )
    connection = get_or_create_connection_by_session_id(session, payload.session_id)
    stored_media_url = payload.media_url
    if stored_media_url and stored_media_url.startswith("data:"):
        mimetype = stored_media_url.split(";")[0].removeprefix("data:")
        data_b64 = stored_media_url.split(",", 1)[1]
        stored_media_url = save_base64_media(data_b64, mimetype)
    create_outbound_message_for_contact(
        session,
        phone_number=payload.recipient_phone,
        display_name=payload.recipient_name,
        body=payload.body,
        media_url=stored_media_url,
        message_type=payload.message_type,
        provider_message_id=payload.provider_message_id,
        delivery_status="sent",
        connection_id=connection.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@message_router.get("/media/{filename}")
def serve_media(filename: str) -> FileResponse:
    path = get_media_path(filename)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
    return FileResponse(path)


@internal_router.post("/internal/bridge/ack", status_code=status.HTTP_204_NO_CONTENT)
def receive_bridge_ack(
    payload: BridgeAck,
    x_bridge_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Response:
    settings = get_settings()
    if x_bridge_key != settings.bridge_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bridge key")

    update_message_delivery_status(session, payload.provider_message_id, payload.delivery_status)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ServicePushRequest(BaseModel):
    user_phone: str
    message: str
    source_service: str
    quick_replies: list[str] = []


@internal_router.post("/internal/push", status_code=status.HTTP_204_NO_CONTENT)
def receive_service_push(
    payload: ServicePushRequest,
    x_alfred_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Response:
    """Downstream services (OurCents, Nudge) call this to push a message to a user."""
    settings = get_settings()
    valid_keys = {
        k for k in [settings.ourcents_api_key, settings.nudge_api_key, settings.alfred_internal_key]
        if k
    }
    if not valid_keys or x_alfred_api_key not in valid_keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid key")

    body = payload.message
    if payload.quick_replies:
        body += "\n\n" + "  ".join(f"[{q}]" for q in payload.quick_replies)

    # Upsert contact and conversation so push works even before the user has
    # messaged Alfred (solves bootstrap problem for Nudge reminders etc.)
    from app.models.chat import WhatsAppConnection
    from app.repositories.chat_repository import create_or_get_contact, get_or_create_conversation

    phone = normalize_phone_number(payload.user_phone)
    contact = create_or_get_contact(session, phone, display_name=None)
    conv = get_or_create_conversation(session, contact)

    provider_message_id: str | None = None
    if settings.whatsapp_mode == "bridge":
        # Prefer the conversation's linked connection; fall back to any active bridge session
        conn_record = session.get(WhatsAppConnection, conv.connection_id) if conv.connection_id else None
        if conn_record is None:
            live = {s["id"]: s for s in list_bridge_sessions()}
            conn_record = next(
                (session.get(WhatsAppConnection, c.id)
                 for c in list_connections(session)
                 if live.get(c.bridge_session_id, {}).get("status") == "connected"),
                None,
            )
        if conn_record:
            provider_message_id = send_text_via_bridge(conn_record.bridge_session_id, contact.phone_number, body)
        else:
            logger.warning("Bridge push skipped — no active bridge connection found")
    else:
        from app.services.dispatch_service import _send_cloud_reply
        _send_cloud_reply(contact.phone_number, body, settings)

    # Persist outbound message so it appears in the conversation UI
    from datetime import datetime, timezone as _tz
    from app.models.chat import Message as _Message
    try:
        msg = _Message(
            conversation_id=conv.id,
            provider_message_id=provider_message_id,
            direction="outbound",
            message_type="text",
            body=body,
            delivery_status="sent" if provider_message_id else "queued",
        )
        session.add(msg)
        conv.updated_at = datetime.now(_tz.utc)
        session.add(conv)
        session.commit()
    except Exception as exc:
        logger.warning("Failed to persist push message: %s", exc)

    return Response(status_code=status.HTTP_204_NO_CONTENT)

# ── Log viewer (admin only) ───────────────────────────────────────────────────

_file_parents = Path(__file__).resolve().parents
_LOG_DIR = Path(os.environ.get('LOG_DIR') or (
    _file_parents[4] / '.logs' if len(_file_parents) > 4 else Path('/tmp/alfred-logs')
))
_ALLOWED_SERVICES = {"gateway", "ourcents", "nudge", "bridge", "frontend"}

@auth_router.get("/logs/{service}", dependencies=[Depends(get_current_admin)])
def get_logs(service: str, lines: int = 300):
    if service not in _ALLOWED_SERVICES:
        raise HTTPException(status_code=404, detail="Unknown service")
    log_file = _LOG_DIR / f"{service}.log"
    if not log_file.exists():
        return {"service": service, "lines": []}
    text = log_file.read_text(errors="replace")
    all_lines = text.splitlines()
    return {"service": service, "lines": all_lines[-lines:]}
