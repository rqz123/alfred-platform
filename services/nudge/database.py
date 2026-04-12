from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, JSON
)

import os
DATABASE_URL = os.environ.get("NUDGE_DATABASE_URL", "sqlite:////data/nudge.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

metadata = MetaData()

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
    Column("status", String, nullable=False, default="active"),
    Column("lastFiredAt", String, nullable=True),
    Column("nextFireAt", String, nullable=True),
    Column("createdAt", String, nullable=False),
    Column("updatedAt", String, nullable=False),
)


def create_tables():
    metadata.create_all(engine)
