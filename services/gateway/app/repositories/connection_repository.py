from sqlmodel import Session, select

from app.models.chat import WhatsAppConnection


def list_connections(session: Session) -> list[WhatsAppConnection]:
    return list(session.exec(select(WhatsAppConnection).order_by(WhatsAppConnection.created_at.asc())).all())


def create_connection_record(session: Session, bridge_session_id: str, label: str | None) -> WhatsAppConnection:
    connection = WhatsAppConnection(bridge_session_id=bridge_session_id, label=label)
    session.add(connection)
    session.commit()
    session.refresh(connection)
    return connection


def get_connection_by_session_id(session: Session, bridge_session_id: str) -> WhatsAppConnection | None:
    return session.exec(
        select(WhatsAppConnection).where(WhatsAppConnection.bridge_session_id == bridge_session_id)
    ).first()


def get_or_create_connection_by_session_id(session: Session, bridge_session_id: str) -> WhatsAppConnection:
    connection = get_connection_by_session_id(session, bridge_session_id)
    if connection is not None:
        return connection
    connection = WhatsAppConnection(bridge_session_id=bridge_session_id)
    session.add(connection)
    session.commit()
    session.refresh(connection)
    return connection


def get_connection_by_id(session: Session, connection_id: int) -> WhatsAppConnection | None:
    return session.get(WhatsAppConnection, connection_id)


def delete_connection_record(session: Session, connection_id: int) -> bool:
    connection = session.get(WhatsAppConnection, connection_id)
    if connection is None:
        return False
    session.delete(connection)
    session.commit()
    return True
