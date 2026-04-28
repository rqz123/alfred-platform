from sqlmodel import Session, SQLModel, create_engine, text

from app.core.config import get_settings
from app.models.account import AlfredFamily, AlfredUser  # noqa: F401 — registers tables
from app.models.auth import AdminUser
from app.models.chat import Contact, Conversation, Message


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Apply additive schema migrations for columns added after initial create."""
    with Session(engine) as session:
        try:
            session.exec(text("ALTER TABLE conversation ADD COLUMN unread_count INTEGER NOT NULL DEFAULT 0"))
            session.commit()
        except Exception:
            session.rollback()  # column already exists — safe to ignore


def get_session():
    with Session(engine) as session:
        yield session