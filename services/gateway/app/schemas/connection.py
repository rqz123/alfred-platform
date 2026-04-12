from datetime import datetime

from pydantic import BaseModel


class ConnectionCreate(BaseModel):
    label: str | None = None
    session_id: str | None = None


class ConnectionRead(BaseModel):
    id: int
    bridge_session_id: str
    label: str | None
    created_at: datetime
    status: str = "offline"
    qr_code_data_url: str | None = None
    connected_phone: str | None = None
    connected_name: str | None = None
    last_error: str | None = None
