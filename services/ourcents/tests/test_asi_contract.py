"""
ASI contract tests for OurCents /alfred/execute endpoint.

Uses a real (temp-file) SQLite DB + seeded phone_mapping.
Calls alfred_execute() directly to bypass FastAPI's DI and auth middleware.
No network, no Docker required.
"""

import base64
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from storage.database import Database
from app.api.routes import AlfredExecuteRequest, alfred_execute

PHONE = "8613900001234"


# ─────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────

@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    database = Database(path)
    database._initialize_schema()
    yield database
    os.unlink(path)


@pytest.fixture
def seeded_db(db):
    """DB with a family, user, and phone mapping pre-populated."""
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO families (name, created_at) VALUES (?, datetime('now'))",
            ("Test Family",),
        )
        family_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            ("testuser", "test@example.com", "hash"),
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO family_members (family_id, user_id, role) VALUES (?, ?, ?)",
            (family_id, user_id, "admin"),
        )
        conn.execute(
            "INSERT INTO phone_mappings (phone, user_id, family_id) VALUES (?, ?, ?)",
            (PHONE, user_id, family_id),
        )
    return db, family_id, user_id


@pytest.fixture
def mock_file_storage():
    return MagicMock()


# ─────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────

def _req(intent, entities=None, phone=PHONE):
    return AlfredExecuteRequest(
        request_id="test-req",
        user_id="user1",
        whatsapp_id=f"+{phone}",
        intent=intent,
        entities=entities or {},
    )


# ─────────────────────────────────────────────────────
# add_expense
# ─────────────────────────────────────────────────────

class TestAddExpense:
    @pytest.mark.asyncio
    async def test_with_amount_returns_success(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(_req("add_expense", {"amount": 50.0}), db=db, file_storage=mock_file_storage)
        assert resp.status == "success"
        assert "50" in resp.message

    @pytest.mark.asyncio
    async def test_without_amount_returns_insufficient_data(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(_req("add_expense"), db=db, file_storage=mock_file_storage)
        assert resp.status == "error"
        assert resp.error_code == "INSUFFICIENT_DATA"

    @pytest.mark.asyncio
    async def test_unbound_phone_returns_unauthorized(self, db, mock_file_storage):
        resp = await alfred_execute(
            _req("add_expense", {"amount": 50.0}, phone="9999999"),
            db=db, file_storage=mock_file_storage,
        )
        assert resp.status == "error"
        assert resp.error_code == "UNAUTHORIZED"


# ─────────────────────────────────────────────────────
# add_income
# ─────────────────────────────────────────────────────

class TestAddIncome:
    @pytest.mark.asyncio
    async def test_with_amount_returns_success(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(_req("add_income", {"amount": 5000.0}), db=db, file_storage=mock_file_storage)
        assert resp.status == "success"
        assert "5000" in resp.message

    @pytest.mark.asyncio
    async def test_without_amount_returns_insufficient_data(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(_req("add_income"), db=db, file_storage=mock_file_storage)
        assert resp.status == "error"
        assert resp.error_code == "INSUFFICIENT_DATA"


# ─────────────────────────────────────────────────────
# get_balance
# ─────────────────────────────────────────────────────

class TestGetBalance:
    @pytest.mark.asyncio
    async def test_balance_shows_income_expense_net(self, seeded_db, mock_file_storage):
        db, family_id, user_id = seeded_db
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO income_entries "
                "  (family_id, user_id, amount, currency, category, source, income_date) "
                "VALUES (?, ?, ?, ?, ?, ?, date('now'))",
                (family_id, user_id, 1000.0, "CNY", "salary", "whatsapp"),
            )
        resp = await alfred_execute(_req("get_balance"), db=db, file_storage=mock_file_storage)
        assert resp.status == "success"
        assert "Income" in resp.message
        assert "Expense" in resp.message
        assert "Net" in resp.message


# ─────────────────────────────────────────────────────
# monthly_report
# ─────────────────────────────────────────────────────

class TestMonthlyReport:
    @pytest.mark.asyncio
    async def test_returns_monthly_report(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(_req("monthly_report"), db=db, file_storage=mock_file_storage)
        assert resp.status == "success"
        assert "Monthly report" in resp.message


# ─────────────────────────────────────────────────────
# set_budget
# ─────────────────────────────────────────────────────

class TestSetBudget:
    @pytest.mark.asyncio
    async def test_with_category_and_amount(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(
            _req("set_budget", {"category": "food", "amount": 1000.0}),
            db=db, file_storage=mock_file_storage,
        )
        assert resp.status == "success"
        assert "food" in resp.message
        assert "1000" in resp.message

    @pytest.mark.asyncio
    async def test_upsert_is_idempotent(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        await alfred_execute(_req("set_budget", {"category": "food", "amount": 1000.0}), db=db, file_storage=mock_file_storage)
        resp = await alfred_execute(_req("set_budget", {"category": "food", "amount": 1500.0}), db=db, file_storage=mock_file_storage)
        assert resp.status == "success"
        assert "1500" in resp.message

    @pytest.mark.asyncio
    async def test_without_amount_returns_insufficient_data(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(_req("set_budget", {"category": "food"}), db=db, file_storage=mock_file_storage)
        assert resp.status == "error"
        assert resp.error_code == "INSUFFICIENT_DATA"


# ─────────────────────────────────────────────────────
# process_receipt_image
# ─────────────────────────────────────────────────────

class TestProcessReceiptImage:
    @pytest.mark.asyncio
    async def test_without_image_data_returns_insufficient_data(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(_req("process_receipt_image"), db=db, file_storage=mock_file_storage)
        assert resp.status == "error"
        assert resp.error_code == "INSUFFICIENT_DATA"

    @pytest.mark.asyncio
    async def test_with_valid_image_calls_ingestion_service(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        image_b64 = base64.b64encode(b"fake-image-bytes").decode()

        mock_receipt_svc = AsyncMock()
        mock_receipt_svc.process_receipt_upload.return_value = (
            "success",
            42,
            {"merchant_name": "Starbucks", "total_amount": 38.0, "category": "food"},
        )

        with patch("app.api.routes.ReceiptIngestionService", return_value=mock_receipt_svc):
            resp = await alfred_execute(
                _req("process_receipt_image", {"image_data": image_b64, "mime_type": "image/jpeg"}),
                db=db, file_storage=mock_file_storage,
            )

        assert resp.status == "success"
        assert "Starbucks" in resp.message
        assert "38" in resp.message


# ─────────────────────────────────────────────────────
# Unknown intent
# ─────────────────────────────────────────────────────

class TestUnknownIntent:
    @pytest.mark.asyncio
    async def test_unknown_intent_returns_not_found(self, seeded_db, mock_file_storage):
        db, _, _ = seeded_db
        resp = await alfred_execute(_req("foo_bar"), db=db, file_storage=mock_file_storage)
        assert resp.status == "error"
        assert resp.error_code == "NOT_FOUND"
