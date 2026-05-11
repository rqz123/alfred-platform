import json
import logging
import uuid
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, JSON, Integer
)

import os

logger = logging.getLogger("thread")

DATABASE_URL = (
    os.environ.get("THREAD_DATABASE_URL", "")
    or os.environ.get("NUDGE_DATABASE_URL", "sqlite:////data/nudge.db")
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

metadata = MetaData()

threads = Table(
    "threads",
    metadata,
    Column("id", String, primary_key=True),
    Column("shortId", Integer, nullable=True),
    Column("title", String, nullable=True),
    Column("content", Text, nullable=False),
    Column("category", String, nullable=True),     # pro | life | emo | routine
    Column("tags", JSON, nullable=True),
    Column("entities", JSON, nullable=True),       # {"people": [], "places": [], "orgs": []}
    Column("triggerSource", String, nullable=True),
    Column("trigger", Text, nullable=True),        # JSON: {type, fire_at, cron, location, ack_status, ack_timeout_at}
    Column("snoozeCount", Integer, nullable=True, default=0),
    Column("source", String, nullable=True),       # whatsapp | web | voice | geofence
    Column("priority", String, nullable=True),     # high | normal | low
    Column("locationTag", String, nullable=True),
    Column("status", String, nullable=False, default="active"),  # active | sleeping | archived
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


def _migrate_reminders_to_threads(conn) -> int:
    """Migrate reminders rows into threads as trigger-bearing threads. Idempotent."""
    from sqlalchemy import text
    tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    if "reminders" not in tables:
        return 0
    migrated_markers = {r[0] for r in conn.execute(text(
        "SELECT locationTag FROM threads WHERE source='__migrated_reminder__'"
    ))}
    rows = conn.execute(text("SELECT * FROM reminders")).mappings().all()
    count = 0
    for r in rows:
        if r["id"] in migrated_markers:
            continue
        ack_map = {
            "active": "pending", "paused": "pending",
            "awaiting": "awaiting", "done": "acknowledged",
            "expired": "expired",
        }
        cron = r.get("cronExpression")
        fire_at = r.get("fireAt") or r.get("nextFireAt")
        trigger = {
            "type": "recurring" if cron else "once",
            "fire_at": fire_at,
            "cron": cron,
            "location": None,
            "ack_status": ack_map.get(r.get("status", "active"), "pending"),
            "ack_timeout_at": None,
        }
        thread_status_map = {
            "active": "active", "paused": "active",
            "awaiting": "active", "done": "sleeping", "expired": "sleeping",
        }
        src = r.get("triggerSource") or "__unknown__"
        max_sid = conn.execute(text(
            "SELECT MAX(shortId) FROM threads WHERE triggerSource=:src"
        ), {"src": src}).scalar()
        next_sid = (max_sid or 0) + 1
        title = r.get("title") or ""
        body = r.get("body") or ""
        content = f"{title}\n{body}".strip() if body and body != title else title
        conn.execute(text("""
            INSERT INTO threads
              (id, shortId, title, content, category, trigger, snoozeCount,
               source, triggerSource, status, createdAt, updatedAt, locationTag)
            VALUES
              (:id, :sid, :title, :content, 'routine', :trigger, 0,
               '__migrated_reminder__', :src, :status, :created, :updated, :orig_id)
        """), {
            "id": str(uuid.uuid4()),
            "sid": next_sid,
            "title": title,
            "content": content,
            "trigger": json.dumps(trigger),
            "src": src,
            "status": thread_status_map.get(r.get("status", "active"), "active"),
            "created": r.get("createdAt", ""),
            "updated": r.get("updatedAt", ""),
            "orig_id": r["id"],
        })
        count += 1
    if count > 0:
        conn.commit()
    return count


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
            thread_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(threads)"))}
            new_thread_cols = [
                ('shortId',     'ALTER TABLE threads ADD COLUMN "shortId" INTEGER'),
                ('title',       'ALTER TABLE threads ADD COLUMN "title" VARCHAR'),
                ('entities',    'ALTER TABLE threads ADD COLUMN "entities" TEXT'),
                ('category',    'ALTER TABLE threads ADD COLUMN "category" TEXT DEFAULT "life"'),
                ('trigger',     'ALTER TABLE threads ADD COLUMN "trigger" TEXT'),
                ('snoozeCount', 'ALTER TABLE threads ADD COLUMN "snoozeCount" INTEGER DEFAULT 0'),
                ('source',      'ALTER TABLE threads ADD COLUMN "source" TEXT DEFAULT "whatsapp"'),
                ('priority',    'ALTER TABLE threads ADD COLUMN "priority" TEXT'),
                ('locationTag', 'ALTER TABLE threads ADD COLUMN "locationTag" TEXT'),
            ]
            for col_name, ddl in new_thread_cols:
                if col_name not in thread_cols:
                    conn.execute(text(ddl))
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
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(reminders)"))}
            reminder_cols = [
                ('pushRetries',  'ALTER TABLE reminders ADD COLUMN "pushRetries" VARCHAR DEFAULT "0"'),
                ('shortName',    'ALTER TABLE reminders ADD COLUMN "shortName" VARCHAR'),
                ('ackRetries',   'ALTER TABLE reminders ADD COLUMN "ackRetries" VARCHAR DEFAULT "0"'),
                ('firstFiredAt', 'ALTER TABLE reminders ADD COLUMN "firstFiredAt" VARCHAR'),
            ]
            for col_name, ddl in reminder_cols:
                if col_name not in cols:
                    conn.execute(text(ddl))
                    conn.commit()
        except Exception:
            pass

    with engine.connect() as conn:
        migrated = _migrate_reminders_to_threads(conn)
    if migrated > 0:
        logger.info("Migrated %d reminder(s) to threads", migrated)
