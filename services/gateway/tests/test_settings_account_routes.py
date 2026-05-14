"""
Simulation coverage for Settings/Admin Panel flows.

These tests exercise the backend routes used by:
- Settings -> Alfred Bot setup/reconnect/remove
- Admin Panel -> families add/delete
- Admin Panel -> members add/assign/delete
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ALFRED_INTERNAL_KEY", "test-internal-key")
os.environ.setdefault("OURCENTS_API_KEY", "test-ourcents-key")
os.environ.setdefault("NUDGE_API_KEY", "test-nudge-key")
os.environ.setdefault("WHATSAPP_MODE", "bridge")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_session
from app.models.account import AlfredFamily, AlfredUser
from app.models.auth import AdminUser
from app.models.chat import WhatsAppConnection


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def client(db_engine):
    from app.main import app

    def override_session():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    get_settings.cache_clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture()
def admin_phone(client):
    resp = client.post(
        "/api/alfred/bootstrap",
        json={
            "family_name": "Primary Family",
            "admin_phone": "+14080000001",
            "admin_display_name": "Admin",
        },
    )
    assert resp.status_code == 200, resp.text
    return "+14080000001"


@pytest.fixture()
def auth_headers(db_engine):
    with Session(db_engine) as session:
        session.add(AdminUser(username="admin", password_hash="not-used"))
        session.commit()
    token = create_access_token("admin")
    return {"Authorization": f"Bearer {token}"}


def test_settings_bot_connection_setup_reconnect_remove(client, auth_headers, monkeypatch):
    import app.api.routes as routes

    bridge_sessions: dict[str, dict] = {}
    deleted_sessions: list[str] = []

    def fake_create_bridge_session(session_id: str):
        bridge_sessions[session_id] = {
            "id": session_id,
            "status": "qr_ready",
            "qr_code_data_url": "data:image/png;base64,test-qr",
            "connected_phone": None,
            "connected_name": None,
            "last_error": None,
        }
        return bridge_sessions[session_id]

    def fake_list_bridge_sessions():
        return list(bridge_sessions.values())

    def fake_delete_bridge_session(session_id: str):
        deleted_sessions.append(session_id)
        bridge_sessions.pop(session_id, None)

    monkeypatch.setattr(routes, "create_bridge_session", fake_create_bridge_session)
    monkeypatch.setattr(routes, "list_bridge_sessions", fake_list_bridge_sessions)
    monkeypatch.setattr(routes, "delete_bridge_session", fake_delete_bridge_session)

    create_resp = client.post(
        "/api/connections",
        json={"label": "Alfred Bot"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    first = create_resp.json()
    assert first["label"] == "Alfred Bot"
    assert first["status"] == "qr_ready"
    assert first["qr_code_data_url"] == "data:image/png;base64,test-qr"

    list_resp = client.get("/api/connections", headers=auth_headers)
    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json()[0]["status"] == "qr_ready"

    delete_resp = client.delete(f"/api/connections/{first['id']}", headers=auth_headers)
    assert delete_resp.status_code == 204, delete_resp.text
    assert first["bridge_session_id"] in deleted_sessions

    reconnect_resp = client.post(
        "/api/connections",
        json={"label": "Alfred Bot"},
        headers=auth_headers,
    )
    assert reconnect_resp.status_code == 201, reconnect_resp.text
    second = reconnect_resp.json()
    assert second["id"] != first["id"]
    assert second["status"] == "qr_ready"


def test_admin_family_and_member_add_assign_delete(client, admin_phone):
    create_family = client.post(
        "/api/alfred/families",
        json={"name": "Travel Family"},
        headers={"X-Alfred-Phone": admin_phone},
    )
    assert create_family.status_code == 201, create_family.text
    family_id = create_family.json()["id"]

    add_member = client.post(
        "/api/alfred/users",
        json={"phone": "+14080000002", "display_name": "Member"},
        headers={"X-Alfred-Phone": admin_phone},
    )
    assert add_member.status_code == 201, add_member.text
    assert add_member.json()["family_id"] is None

    assign_member = client.patch(
        "/api/alfred/users/%2B14080000002",
        json={"family_id": family_id},
        headers={"X-Alfred-Phone": admin_phone},
    )
    assert assign_member.status_code == 200, assign_member.text
    assert assign_member.json()["family_id"] == family_id

    detail = client.get(
        f"/api/alfred/families/{family_id}",
        headers={"X-Alfred-Phone": admin_phone},
    )
    assert detail.status_code == 200, detail.text
    assert [m["phone"] for m in detail.json()["members"]] == ["+14080000002"]

    delete_member = client.delete(
        "/api/alfred/users/%2B14080000002",
        headers={"X-Alfred-Phone": admin_phone},
    )
    assert delete_member.status_code == 204, delete_member.text

    delete_family = client.delete(
        f"/api/alfred/families/{family_id}",
        headers={"X-Alfred-Phone": admin_phone},
    )
    assert delete_family.status_code == 204, delete_family.text

    users = client.get("/api/alfred/users", headers={"X-Alfred-Phone": admin_phone})
    assert users.status_code == 200, users.text
    assert [u["phone"] for u in users.json()] == [admin_phone]


def test_deleting_family_unassigns_existing_members(client, admin_phone):
    family = client.post(
        "/api/alfred/families",
        json={"name": "Temporary Family"},
        headers={"X-Alfred-Phone": admin_phone},
    ).json()

    member = client.post(
        "/api/alfred/users",
        json={
            "phone": "+14080000003",
            "display_name": "Assigned Member",
            "family_id": family["id"],
        },
        headers={"X-Alfred-Phone": admin_phone},
    ).json()
    assert member["family_id"] == family["id"]

    resp = client.delete(
        f"/api/alfred/families/{family['id']}",
        headers={"X-Alfred-Phone": admin_phone},
    )
    assert resp.status_code == 204, resp.text

    updated = client.get(
        "/api/alfred/users/%2B14080000003",
        headers={"X-Alfred-Phone": admin_phone},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["family_id"] is None
