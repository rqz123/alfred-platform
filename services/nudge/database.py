from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, JSON, Integer
)

import os
DATABASE_URL = os.environ.get("NUDGE_DATABASE_URL", "sqlite:////data/nudge.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

metadata = MetaData()

notes = Table(
    "notes",
    metadata,
    Column("id", String, primary_key=True),
    Column("shortId", Integer, nullable=True),    # user-scoped auto-increment, e.g. 42
    Column("title", String, nullable=True),       # brief LLM-generated title
    Column("content", Text, nullable=False),
    Column("tags", JSON, nullable=True),
    Column("entities", JSON, nullable=True),      # {"people": [], "places": [], "orgs": []}
    Column("triggerSource", String, nullable=True),
    Column("status", String, nullable=False, default="active"),  # active | archived
    Column("createdAt", String, nullable=False),
    Column("updatedAt", String, nullable=False),
)

note_links = Table(
    "note_links",
    metadata,
    Column("id", String, primary_key=True),
    Column("note_id", String, nullable=False),
    Column("linked_note_id", String, nullable=False),
    Column("created_by", String, nullable=True),   # phone
    Column("createdAt", String, nullable=False),
)

reminders = Table(
    "reminders",
    metadata,
    Column("id", String, primary_key=True),
    Column("title", String, nullable=False),
    Column("body", Text, nullable=True),
    Column("type", String, nullable=False),          # once | recurring | event
    Column("fireAt", String, nullable=True),
    Column("cronExpression", String, nullable=True),
    Column("timezone", String, nullable=False),
    Column("triggerSource", String, nullable=True),
    Column("triggerCondition", JSON, nullable=True),
    Column("shortName", String, nullable=True),
    Column("status", String, nullable=False, default="active"),
    Column("lastFiredAt", String, nullable=True),
    Column("nextFireAt", String, nullable=True),
    Column("pushRetries", String, nullable=True, default="0"),  # tracks push attempt count
    Column("ackRetries", String, nullable=True, default="0"),    # re-fire count awaiting user ack
    Column("firstFiredAt", String, nullable=True),               # when reminder first fired
    Column("createdAt", String, nullable=False),
    Column("updatedAt", String, nullable=False),
)


def create_tables():
    metadata.create_all(engine)
    # Migrate: add pushRetries if it doesn't exist yet
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            # Migrate notes table
            note_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(notes)"))]
            if "shortId" not in note_cols:
                conn.execute(text('ALTER TABLE notes ADD COLUMN "shortId" INTEGER'))
                conn.commit()
            if "title" not in note_cols:
                conn.execute(text('ALTER TABLE notes ADD COLUMN "title" VARCHAR'))
                conn.commit()
            if "entities" not in note_cols:
                conn.execute(text('ALTER TABLE notes ADD COLUMN "entities" TEXT'))
                conn.commit()
        except Exception:
            pass
        try:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(reminders)"))]
            if "pushRetries" not in cols:
                conn.execute(text('ALTER TABLE reminders ADD COLUMN "pushRetries" VARCHAR DEFAULT "0"'))
                conn.commit()
            if "shortName" not in cols:
                conn.execute(text('ALTER TABLE reminders ADD COLUMN "shortName" VARCHAR'))
                conn.commit()
            if "ackRetries" not in cols:
                conn.execute(text('ALTER TABLE reminders ADD COLUMN "ackRetries" VARCHAR DEFAULT "0"'))
                conn.commit()
            if "firstFiredAt" not in cols:
                conn.execute(text('ALTER TABLE reminders ADD COLUMN "firstFiredAt" VARCHAR'))
                conn.commit()
        except Exception:
            pass
