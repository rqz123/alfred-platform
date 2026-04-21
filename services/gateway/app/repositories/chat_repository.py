from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.chat import Contact, Conversation, Message
from app.schemas.chat import ConversationCreate, ConversationRead, MessageCreate, MessageRead


def list_conversations(session: Session) -> list[ConversationRead]:
    conversations = session.exec(select(Conversation).order_by(Conversation.updated_at.desc())).all()
    items: list[ConversationRead] = []

    for conversation in conversations:
        contact = session.get(Contact, conversation.contact_id)
        if contact is None:
            continue

        latest = session.exec(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
        ).first()

        latest_msg_preview: str | None = None
        if latest:
            if latest.message_type == "image":
                latest_msg_preview = latest.body or "📷 Image"
            elif latest.message_type in ("audio", "ptt"):
                latest_msg_preview = "🎵 Voice message"
            else:
                latest_msg_preview = latest.body

        items.append(
            ConversationRead(
                id=conversation.id,
                contact_name=contact.display_name,
                phone_number=contact.phone_number,
                updated_at=conversation.updated_at,
                latest_message=latest_msg_preview,
                latest_message_type=latest.message_type if latest else None,
                connection_id=conversation.connection_id,
                unread_count=conversation.unread_count,
            )
        )

    return items


def get_conversation_or_404(session: Session, conversation_id: int) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


def list_conversation_messages(session: Session, conversation_id: int) -> list[MessageRead]:
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    ).all()
    return [MessageRead.model_validate(message) for message in messages]


def create_outbound_message(
    session: Session,
    conversation: Conversation,
    payload: MessageCreate,
) -> MessageRead:
    stored_message_type = "audio" if payload.send_as_voice else payload.message_type
    message = Message(
        conversation_id=conversation.id,
        direction="outbound",
        provider_message_id=None,
        message_type=stored_message_type,
        body=payload.body,
        media_url=payload.media_url,
        transcript=payload.body if payload.send_as_voice else None,
        delivery_status="queued",
    )
    session.add(message)
    conversation.updated_at = datetime.now(timezone.utc)
    session.add(conversation)
    session.commit()
    session.refresh(message)
    return MessageRead.model_validate(message)


def create_outbound_message_for_contact(
    session: Session,
    phone_number: str,
    display_name: str | None,
    body: str | None,
    message_type: str = "text",
    provider_message_id: str | None = None,
    delivery_status: str = "queued",
    connection_id: int | None = None,
    media_url: str | None = None,
) -> MessageRead:
    contact = create_or_get_contact(session, phone_number, display_name)
    conversation = get_or_create_conversation(session, contact, connection_id=connection_id)

    existing = None
    if provider_message_id:
        existing = session.exec(
            select(Message).where(Message.provider_message_id == provider_message_id)
        ).first()
    if existing is not None:
        return MessageRead.model_validate(existing)

    message = Message(
        conversation_id=conversation.id,
        direction="outbound",
        provider_message_id=provider_message_id,
        message_type=message_type,
        body=body,
        media_url=media_url,
        delivery_status=delivery_status,
    )
    session.add(message)
    conversation.updated_at = datetime.now(timezone.utc)
    session.add(conversation)
    session.commit()
    session.refresh(message)
    return MessageRead.model_validate(message)


def create_or_get_contact(session: Session, phone_number: str, display_name: str | None) -> Contact:
    contact = session.exec(select(Contact).where(Contact.phone_number == phone_number)).first()
    if contact is not None:
        if display_name and contact.display_name != display_name:
            contact.display_name = display_name
            session.add(contact)
            session.commit()
            session.refresh(contact)
        return contact

    contact = Contact(display_name=display_name or phone_number, phone_number=phone_number)
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


def get_or_create_conversation(session: Session, contact: Contact, connection_id: int | None = None) -> Conversation:
    # One conversation per contact regardless of which bridge connection delivered it.
    conversation = session.exec(
        select(Conversation)
        .where(Conversation.contact_id == contact.id)
    ).first()
    if conversation is not None:
        # Keep connection_id up to date if a newer one is provided.
        if connection_id is not None and conversation.connection_id != connection_id:
            conversation.connection_id = connection_id
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
        return conversation

    conversation = Conversation(contact_id=contact.id, connection_id=connection_id)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def create_or_get_conversation_for_contact(
    session: Session,
    payload: ConversationCreate,
) -> ConversationRead:
    contact = create_or_get_contact(session, payload.phone_number, payload.contact_name)
    conversation = get_or_create_conversation(session, contact, connection_id=payload.connection_id)
    latest = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
    ).first()

    return ConversationRead(
        id=conversation.id,
        contact_name=contact.display_name,
        phone_number=contact.phone_number,
        updated_at=conversation.updated_at,
        latest_message=latest.body if latest else None,
        latest_message_type=latest.message_type if latest else None,
        connection_id=conversation.connection_id,
    )


def create_inbound_message_for_contact(
    session: Session,
    phone_number: str,
    display_name: str | None,
    provider_message_id: str | None,
    message_type: str,
    body: str | None,
    media_url: str | None,
    transcript: str | None = None,
    connection_id: int | None = None,
) -> MessageRead:
    contact = create_or_get_contact(session, phone_number, display_name)
    conversation = get_or_create_conversation(session, contact, connection_id=connection_id)
    return create_inbound_message(
        session,
        conversation,
        provider_message_id=provider_message_id,
        message_type=message_type,
        body=body,
        media_url=media_url,
        transcript=transcript,
    )


def mark_conversation_read(session: Session, conversation_id: int) -> None:
    conversation = session.get(Conversation, conversation_id)
    if conversation and conversation.unread_count > 0:
        conversation.unread_count = 0
        session.add(conversation)
        session.commit()


def create_inbound_message(
    session: Session,
    conversation: Conversation,
    provider_message_id: str | None,
    message_type: str,
    body: str | None,
    media_url: str | None,
    transcript: str | None = None,
) -> MessageRead:
    existing = None
    if provider_message_id:
        existing = session.exec(
            select(Message).where(Message.provider_message_id == provider_message_id)
        ).first()
    if existing is not None:
        return MessageRead.model_validate(existing)

    message = Message(
        conversation_id=conversation.id,
        provider_message_id=provider_message_id,
        direction="inbound",
        message_type=message_type,
        body=body,
        media_url=media_url,
        transcript=transcript,
        delivery_status="delivered",
    )
    session.add(message)
    conversation.updated_at = datetime.now(timezone.utc)
    conversation.unread_count = (conversation.unread_count or 0) + 1
    session.add(conversation)
    session.commit()
    session.refresh(message)
    return MessageRead.model_validate(message)


def update_message_delivery_status(
    session: Session,
    provider_message_id: str,
    delivery_status: str,
) -> MessageRead | None:
    message = session.exec(
        select(Message).where(Message.provider_message_id == provider_message_id)
    ).first()
    if message is None:
        return None

    message.delivery_status = delivery_status
    session.add(message)
    session.commit()
    session.refresh(message)
    return MessageRead.model_validate(message)


def assign_provider_message_id(
    session: Session,
    message_id: int,
    provider_message_id: str,
    delivery_status: str,
) -> MessageRead:
    message = session.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    message.provider_message_id = provider_message_id
    message.delivery_status = delivery_status
    session.add(message)
    session.commit()
    session.refresh(message)
    return MessageRead.model_validate(message)


def update_message_status_by_id(session: Session, message_id: int, delivery_status: str) -> MessageRead:
    message = session.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    message.delivery_status = delivery_status
    session.add(message)
    session.commit()
    session.refresh(message)
    return MessageRead.model_validate(message)


def clear_conversation_messages(session: Session, conversation: Conversation) -> None:
    messages = session.exec(
        select(Message).where(Message.conversation_id == conversation.id)
    ).all()

    for message in messages:
        session.delete(message)

    conversation.updated_at = datetime.now(timezone.utc)
    session.add(conversation)
    session.commit()


def delete_conversation(session: Session, conversation: Conversation) -> None:
    """Delete all messages then the conversation row itself."""
    messages = session.exec(
        select(Message).where(Message.conversation_id == conversation.id)
    ).all()
    for message in messages:
        session.delete(message)
    session.delete(conversation)
    session.commit()


def delete_all_conversations(session: Session) -> None:
    """Delete every message and every conversation row."""
    messages = session.exec(select(Message)).all()
    for message in messages:
        session.delete(message)
    conversations = session.exec(select(Conversation)).all()
    for conversation in conversations:
        session.delete(conversation)
    session.commit()