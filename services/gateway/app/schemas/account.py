from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    family_name: str
    admin_phone: str
    admin_display_name: str


class BootstrapResponse(BaseModel):
    success: bool
    user_id: str
    family_id: str
    message: str


class UserCreate(BaseModel):
    phone: str
    display_name: Optional[str] = None
    family_id: Optional[str] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    family_id: Optional[str] = None


class UserOut(BaseModel):
    id: str
    phone: str
    display_name: Optional[str]
    role: str
    family_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FamilyCreate(BaseModel):
    name: str


class FamilyUpdate(BaseModel):
    name: str


class FamilyOut(BaseModel):
    id: str
    name: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FamilyDetailOut(FamilyOut):
    members: list[UserOut]


class ResolveResponse(BaseModel):
    user_id: str
    phone: str
    display_name: Optional[str]
    role: str
    family_id: Optional[str]
