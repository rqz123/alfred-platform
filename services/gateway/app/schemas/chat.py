from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConversationRead(BaseModel):
    id: int
    contact_name: str
    phone_number: str
    updated_at: datetime
    latest_message: str | None
    latest_message_type: str | None
    connection_id: int | None = None
    unread_count: int = 0


class MessageCreate(BaseModel):
    message_type: str = "text"
    body: str | None = None
    media_url: str | None = None
    send_as_voice: bool = False


class ConversationCreate(BaseModel):
    phone_number: str
    contact_name: str | None = None
    first_message: str | None = None
    connection_id: int | None = None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    provider_message_id: str | None
    direction: str
    message_type: str
    body: str | None
    media_url: str | None
    transcript: str | None
    delivery_status: str
    created_at: datetime