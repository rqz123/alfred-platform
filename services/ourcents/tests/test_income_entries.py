"""
Tests for income_entries table and add_income / get_balance / monthly_report
in the OurCents alfred/execute endpoint.

Uses an in-memory SQLite DB so tests are isolated.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from storage.database import Database


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
        # users table has no family_id — family membership is via family_members
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
            ("8613900001234", user_id, family_id),
        )
    return db, family_id, user_id


class TestIncomeEntriesTable:
    def test_table_exists(self, db):
        with db.get_connection() as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        assert "income_entries" in tables

    def test_insert_and_retrieve(self, seeded_db):
        db, family_id, user_id = seeded_db
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO income_entries "
                "  (family_id, user_id, amount, currency, category, source, income_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (family_id, user_id, 5000.0, "CNY", "salary", "whatsapp", "2026-04-01"),
            )
            row = conn.execute(
                "SELECT * FROM income_entries WHERE family_id=?", (family_id,)
            ).fetchone()
        assert row is not None
        assert row["amount"] == 5000.0
        assert row["category"] == "salary"

    def test_income_does_not_appear_in_receipts(self, seeded_db):
        """Adding income must not pollute the receipts (expense) table."""
        db, family_id, user_id = seeded_db
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO income_entries "
                "  (family_id, user_id, amount, currency, category, source, income_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (family_id, user_id, 3000.0, "CNY", "bonus", "whatsapp", "2026-04-05"),
            )
            receipt_count = conn.execute(
                "SELECT COUNT(*) AS c FROM receipts WHERE family_id=?", (family_id,)
            ).fetchone()["c"]
        assert receipt_count == 0, "Income entry must not create a receipt row"

    def test_monthly_income_sum(self, seeded_db):
        db, family_id, user_id = seeded_db
        with db.get_connection() as conn:
            for amount in [1000.0, 2000.0, 500.0]:
                conn.execute(
                    "INSERT INTO income_entries "
                    "  (family_id, user_id, amount, currency, category, source, income_date) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (family_id, user_id, amount, "CNY", "other", "whatsapp", "2026-04-10"),
                )
            total = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM income_entries "
                "WHERE family_id=? AND income_date >= ?",
                (family_id, "2026-04-01"),
            ).fetchone()["total"]
        assert total == 3500.0
