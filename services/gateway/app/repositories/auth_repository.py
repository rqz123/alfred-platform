from sqlmodel import Session, select

from app.models.auth import AdminUser


def get_admin_user(session: Session, username: str) -> AdminUser | None:
    statement = select(AdminUser).where(AdminUser.username == username)
    return session.exec(statement).first()