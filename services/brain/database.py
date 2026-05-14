from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, Float, Boolean, Integer, text,
)

from config import get_settings

_settings = get_settings()
engine = create_engine(
    _settings.brain_database_url,
    connect_args={"check_same_thread": False},
)

metadata = MetaData()

brain_events = Table(
    "brain_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("event_action", String, nullable=False),   # CREATE | INVALIDATE | USER_CORRECTION
    Column("event_type", String, nullable=True),      # add_thread | add_expense | …
    Column("entity_id", String, nullable=True),       # for INVALIDATE / USER_CORRECTION
    Column("user_id", String, nullable=True),
    Column("family_id", String, nullable=True),
    Column("entities_json", Text, nullable=True),     # raw entities JSON
    Column("processed", Boolean, nullable=False, default=False),
    Column("created_at", String, nullable=False),
)

weavings = Table(
    "weavings",
    metadata,
    Column("id", String, primary_key=True),
    Column("family_id", String, nullable=False),
    Column("title", String, nullable=True),
    Column("source_thread_id", String, nullable=True),
    Column("source_expense_id", String, nullable=True),
    Column("intent_vector_json", Text, nullable=True),  # {"urgency":…,"social_bond":…,"goal_alignment":…}
    Column("fact_cosine", Float, nullable=True),
    Column("status", String, nullable=False, default="proposed"),  # proposed | confirmed | corrected
    Column("acl_tier", String, nullable=False, server_default="shared"),  # shared | family_private | user_private
    Column("created_at", String, nullable=False),
    Column("confirmed_at", String, nullable=True),
)

nudge_log = Table(
    "nudge_log",
    metadata,
    Column("id", String, primary_key=True),
    Column("family_id", String, nullable=False),
    Column("user_id", String, nullable=True),
    Column("level", Integer, nullable=False, default=1),  # 1-4
    Column("cost", Float, nullable=False, default=0.5),
    Column("sent_at", String, nullable=False),
)

correction_memory = Table(
    "correction_memory",
    metadata,
    Column("id", String, primary_key=True),
    Column("family_id", String, nullable=False),
    Column("source_node_id", String, nullable=False),
    Column("target_node_id", String, nullable=False),
    Column("correction_type", String, nullable=False, default="disconnect"),
    Column("reason", Text, nullable=True),
    Column("penalty_coefficient", Float, nullable=False, default=0.1),
    Column("created_at", String, nullable=False),
)

graph_snapshots = Table(
    "graph_snapshots",
    metadata,
    Column("id", String, primary_key=True),
    Column("family_id", String, nullable=False),
    Column("snapshot_date", String, nullable=False),  # YYYY-MM-DD
    Column("data_json", Text, nullable=False),
    Column("created_at", String, nullable=False),
)

kill_switches = Table(
    "kill_switches",
    metadata,
    Column("family_id", String, primary_key=True),
    Column("active", Boolean, nullable=False, default=False),
    Column("updated_at", String, nullable=False),
)


persona_profiles = Table(
    "persona_profiles",
    metadata,
    Column("id", String, primary_key=True),       # family_id + ":" + user_phone
    Column("family_id", String, nullable=False),
    Column("user_phone", String, nullable=False),
    Column("display_name", String, nullable=True),
    # interaction_rules fields (Patch E)
    Column("implicit_ack_enabled", Boolean, nullable=False, default=False),
    Column("implicit_ack_weight_increment", Float, nullable=False, default=0.05),
    Column("implicit_ack_weight_cap", Float, nullable=False, default=0.4),
    Column("silence_veto_phrase", String, nullable=True),   # e.g. "stop for now"
    Column("inactivity_pause_days", Integer, nullable=False, default=7),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)


def create_tables():
    metadata.create_all(engine)
    _migrate()


def _migrate():
    migrations = [
        'ALTER TABLE weavings ADD COLUMN acl_tier TEXT NOT NULL DEFAULT "shared"',
    ]
    with engine.connect() as conn:
        for ddl in migrations:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists — safe to ignore
