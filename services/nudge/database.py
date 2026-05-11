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

threads = Table(
    "threads",
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

thread_links = Table(
    "thread_links",
    metadata,
    Column("id", String, primary_key=True),
    Column("thread_id", String, nullable=False),
    Column("linked_thread_id", String, nullable=False),
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
    from sqlalchemy import text
    with engine.connect() as conn:
        # Migrate: rename notes → threads, note_links → thread_links
        tables = [row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
        if "notes" in tables and "threads" not in tables:
            conn.execute(text("ALTER TABLE notes RENAME TO threads"))
            conn.commit()
        if "note_links" in tables and "thread_links" not in tables:
            conn.execute(text("ALTER TABLE note_links RENAME TO thread_links"))
            conn.commit()

    metadata.create_all(engine)

    with engine.connect() as conn:
        try:
            thread_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(threads)"))]
            if "shortId" not in thread_cols:
                conn.execute(text('ALTER TABLE threads ADD COLUMN "shortId" INTEGER'))
                conn.commit()
            if "title" not in thread_cols:
                conn.execute(text('ALTER TABLE threads ADD COLUMN "title" VARCHAR'))
                conn.commit()
            if "entities" not in thread_cols:
                conn.execute(text('ALTER TABLE threads ADD COLUMN "entities" TEXT'))
                conn.commit()
        except Exception:
            pass
        try:
            # Rename legacy note_id/linked_note_id columns in thread_links
            link_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(thread_links)"))]
            if "note_id" in link_cols and "thread_id" not in link_cols:
                conn.execute(text("ALTER TABLE thread_links RENAME COLUMN note_id TO thread_id"))
                conn.commit()
            if "linked_note_id" in link_cols and "linked_thread_id" not in link_cols:
                conn.execute(text("ALTER TABLE thread_links RENAME COLUMN linked_note_id TO linked_thread_id"))
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
