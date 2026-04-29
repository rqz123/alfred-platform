import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models.account import AlfredFamily, AlfredUser


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_phone(phone: str) -> str:
    phone = phone.strip()
    if not re.match(r"^\+\d{7,15}$", phone):
        raise ValueError(f"Invalid phone number format: {phone}")
    return phone


# ── Bootstrap ──────────────────────────────────────────────────────────────────

def has_any_user(session: Session) -> bool:
    return session.exec(select(AlfredUser).limit(1)).first() is not None


def bootstrap(
    session: Session,
    family_name: str,
    admin_phone: str,
    admin_display_name: str,
) -> tuple[AlfredUser, AlfredFamily]:
    admin_phone = normalize_phone(admin_phone)
    family_id = _new_id("fam_")
    user_id = _new_id("usr_")

    family = AlfredFamily(id=family_id, name=family_name, created_by=user_id)
    user = AlfredUser(
        id=user_id,
        phone=admin_phone,
        display_name=admin_display_name,
        role="admin",
        family_id=family_id,
    )
    session.add(family)
    session.add(user)
    session.commit()
    session.refresh(family)
    session.refresh(user)
    return user, family


# ── Users ──────────────────────────────────────────────────────────────────────

def get_user_by_phone(session: Session, phone: str) -> Optional[AlfredUser]:
    user = session.exec(select(AlfredUser).where(AlfredUser.phone == phone)).first()
    if user is None and not phone.startswith("+"):
        user = session.exec(select(AlfredUser).where(AlfredUser.phone == "+" + phone)).first()
    return user


def get_user_by_id(session: Session, user_id: str) -> Optional[AlfredUser]:
    return session.get(AlfredUser, user_id)


def list_users(session: Session) -> list[AlfredUser]:
    return list(session.exec(select(AlfredUser).order_by(AlfredUser.created_at)).all())


def count_admins(session: Session) -> int:
    return len(session.exec(select(AlfredUser).where(AlfredUser.role == "admin")).all())


def create_user(
    session: Session,
    phone: str,
    display_name: Optional[str] = None,
    family_id: Optional[str] = None,
) -> AlfredUser:
    phone = normalize_phone(phone)
    user = AlfredUser(
        id=_new_id("usr_"),
        phone=phone,
        display_name=display_name,
        family_id=family_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def update_user(session: Session, user: AlfredUser, **kwargs) -> AlfredUser:
    for k, v in kwargs.items():
        setattr(user, k, v)
    user.updated_at = _utc_now()
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def delete_user(session: Session, user: AlfredUser) -> None:
    session.delete(user)
    session.commit()


# ── Families ───────────────────────────────────────────────────────────────────

def get_family_by_id(session: Session, family_id: str) -> Optional[AlfredFamily]:
    return session.get(AlfredFamily, family_id)


def list_families(session: Session) -> list[AlfredFamily]:
    return list(session.exec(select(AlfredFamily).order_by(AlfredFamily.created_at)).all())


def create_family(
    session: Session,
    name: str,
    created_by: Optional[str] = None,
) -> AlfredFamily:
    family = AlfredFamily(id=_new_id("fam_"), name=name, created_by=created_by)
    session.add(family)
    session.commit()
    session.refresh(family)
    return family


def update_family(session: Session, family: AlfredFamily, **kwargs) -> AlfredFamily:
    for k, v in kwargs.items():
        setattr(family, k, v)
    family.updated_at = _utc_now()
    session.add(family)
    session.commit()
    session.refresh(family)
    return family


def delete_family(session: Session, family: AlfredFamily) -> None:
    members = session.exec(
        select(AlfredUser).where(AlfredUser.family_id == family.id)
    ).all()
    for member in members:
        member.family_id = None
        member.updated_at = _utc_now()
        session.add(member)
    session.delete(family)
    session.commit()


def get_family_members(session: Session, family_id: str) -> list[AlfredUser]:
    return list(
        session.exec(select(AlfredUser).where(AlfredUser.family_id == family_id)).all()
    )
