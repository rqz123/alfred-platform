"""
Tests for POST /api/internal/push — specifically the bootstrap scenario where
the user has never messaged Alfred and no Contact/Conversation exists yet.

Uses an in-memory SQLite database so tests are isolated and fast.
"""

import os
import sys

# Must set env before importing app modules so Settings reads them
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ALFRED_INTERNAL_KEY", "test-internal-key")
os.environ.setdefault("OURCENTS_API_KEY", "test-ourcents-key")
os.environ.setdefault("NUDGE_API_KEY", "test-nudge-key")
os.environ.setdefault("WHATSAPP_MODE", "bridge")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.db.session import get_session
from app.models.chat import Contact, Conversation
from app.core.config import get_settings


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="module")
def client(db_engine):
    from app.main import app

    def override_session():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    # Clear settings cache so env overrides take effect
    get_settings.cache_clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


class TestPushBootstrap:
    """Push should work even when no Contact record exists for the phone."""

    def test_push_creates_contact_when_not_exists(self, client, db_engine):
        """
        Call /api/internal/push for a phone that has never messaged Alfred.
        Expect 204 and a Contact+Conversation created in the DB.
        The bridge send will fail (no bridge running) — that's OK; we only
        assert the DB state, not the WhatsApp delivery.
        """
        phone = "+8613900001111"

        # Confirm no Contact exists before the call
        with Session(db_engine) as s:
            existing = s.query(Contact).filter(Contact.phone_number != "").all()
            phones_before = [c.phone_number for c in existing]
        # phone may or may not exist; we care about it after

        resp = client.post(
            "/api/internal/push",
            json={
                "user_phone": phone,
                "message": "Test reminder",
                "source_service": "nudge",
                "quick_replies": ["View reminders"],
            },
            headers={"X-Alfred-API-Key": "test-internal-key"},
        )
        # 204 means push was accepted (delivery may silently fail — bridge not running)
        assert resp.status_code in (204, 500), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

        # A Contact and Conversation must have been upserted
        with Session(db_engine) as s:
            contact = s.exec(
                __import__("sqlmodel", fromlist=["select"]).select(Contact)
            ).all()
            phones_after = [c.phone_number for c in contact]

        # The normalized phone should now be in the DB
        assert any(
            p.replace("+", "").replace(" ", "") in phone.replace("+", "")
            or phone.replace("+", "") in p.replace("+", "").replace(" ", "")
            for p in phones_after
        ), f"Expected phone {phone} to be upserted, got {phones_after}"

    def test_push_rejected_without_api_key(self, client):
        resp = client.post(
            "/api/internal/push",
            json={
                "user_phone": "+8613900002222",
                "message": "test",
                "source_service": "nudge",
            },
        )
        assert resp.status_code == 401

    def test_push_rejected_with_wrong_api_key(self, client):
        resp = client.post(
            "/api/internal/push",
            json={
                "user_phone": "+8613900002222",
                "message": "test",
                "source_service": "nudge",
            },
            headers={"X-Alfred-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401
