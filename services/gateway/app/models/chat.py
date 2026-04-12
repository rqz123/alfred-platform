from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WhatsAppConnection(SQLModel, table=True):
    __tablename__ = "whatsappconnection"

    id: int | None = Field(default=None, primary_key=True)
    bridge_session_id: str = Field(index=True, unique=True)
    label: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Contact(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    display_name: str
    phone_number: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utc_now)


class Conversation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    contact_id: int = Field(index=True, foreign_key="contact.id")
    connection_id: int | None = Field(default=None, index=True, foreign_key="whatsappconnection.id")
    unread_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    provider_message_id: str | None = Field(default=None, index=True, unique=True)
    direction: str
    message_type: str
    body: str | None = None
    media_url: str | None = None
    transcript: str | None = None
    delivery_status: str = "pending"
    created_at: datetime = Field(default_factory=utc_now)
