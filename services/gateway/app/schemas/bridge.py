from pydantic import BaseModel


class BridgeSessionStatus(BaseModel):
    status: str
    qr_code_data_url: str | None = None
    connected_phone: str | None = None
    connected_name: str | None = None
    last_error: str | None = None


class BridgeInboundMessage(BaseModel):
    session_id: str
    provider_message_id: str
    sender_phone: str
    sender_name: str | None = None
    message_type: str = "text"
    body: str | None = None
    media_url: str | None = None
    transcript: str | None = None


class BridgeOutboundMessage(BaseModel):
    session_id: str
    provider_message_id: str
    recipient_phone: str
    recipient_name: str | None = None
    message_type: str = "text"
    body: str | None = None
    media_url: str | None = None


class BridgeAck(BaseModel):
    session_id: str
    provider_message_id: str
    delivery_status: str