from sqlmodel import select

from app.core.config import get_settings
from app.core.security import get_password_hash
from app.db.session import engine
from app.models.auth import AdminUser
from app.models.chat import Contact, Conversation, Message


def seed_data() -> None:
    settings = get_settings()

    with engine.begin() as connection:
        pass

    from sqlmodel import Session

    with Session(engine) as session:
        admin = session.exec(select(AdminUser)).first()
        if admin is None:
            session.add(
                AdminUser(
                    username=settings.admin_username,
                    password_hash=get_password_hash(settings.admin_password),
                )
            )

        if settings.whatsapp_mode == "bridge":
            session.commit()
            return

        contact = session.exec(select(Contact).where(Contact.phone_number == "+15550000001")).first()
        if contact is None:
            contact = Contact(display_name="Demo Contact", phone_number="+15550000001")
            session.add(contact)
            session.flush()

            conversation = Conversation(contact_id=contact.id)
            session.add(conversation)
            session.flush()

            session.add(
                Message(
                    conversation_id=conversation.id,
                    direction="inbound",
                    message_type="text",
                    body="Hello from WhatsApp.",
                    delivery_status="delivered",
                )
            )

        session.commit()