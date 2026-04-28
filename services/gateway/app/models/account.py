from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AlfredFamily(SQLModel, table=True):
    __tablename__ = "alfred_families"

    id: str = Field(primary_key=True)           # fam_<uuid.hex>
    name: str
    created_by: Optional[str] = Field(default=None)  # usr_<uuid.hex>, no FK to avoid circular ref
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class AlfredUser(SQLModel, table=True):
    __tablename__ = "alfred_users"

    id: str = Field(primary_key=True)           # usr_<uuid.hex>
    phone: str = Field(index=True, unique=True)  # E.164 e.g. +14081234567
    display_name: Optional[str] = None
    role: str = Field(default="user")            # "user" | "admin"
    family_id: Optional[str] = Field(
        default=None,
        index=True,
        foreign_key="alfred_families.id",
        sa_column_kwargs={"onupdate": None},
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
