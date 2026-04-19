"""
ASI contract tests for Nudge /alfred/execute endpoint.

Calls alfred_execute() directly (bypassing auth middleware).
Mocks parse_reminder (async LLM call) and SQLAlchemy engine.
No network, no Docker required.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from routers.nudge import AlfredExecuteRequest, alfred_execute


# ─────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────

def _req(intent, entities=None):
    return AlfredExecuteRequest(
        request_id="test-req",
        user_id="user1",
        whatsapp_id="+8613800000000",
        intent=intent,
        entities=entities or {},
        timestamp="2026-04-13T08:00:00Z",
    )


def _make_conn(rows=None):
    """Return a MagicMock that behaves like a SQLAlchemy connection context manager."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.mappings.return_value.all.return_value = rows or []
    return mock_conn


# ─────────────────────────────────────────────────────
# list_reminders
# ─────────────────────────────────────────────────────

class TestListReminders:
    @pytest.mark.asyncio
    async def test_no_reminders_returns_empty_message(self):
        req = _req("list_reminders")
        mock_conn = _make_conn([])
        with patch("routers.nudge.engine") as mock_engine:
            mock_engine.connect.return_value = mock_conn
            resp = await alfred_execute(req)
        assert resp.status == "success"
        assert "no pending" in resp.message.lower()
        assert "Add reminder" in resp.quick_replies

    @pytest.mark.asyncio
    async def test_with_two_reminders_lists_titles(self):
        req = _req("list_reminders")
        rows = [
            {"id": "1", "title": "Call doctor", "nextFireAt": "2026-04-14T01:00:00", "fireAt": None, "status": "active"},
            {"id": "2", "title": "Buy groceries", "nextFireAt": "2026-04-15T03:30:00", "fireAt": None, "status": "active"},
        ]
        mock_conn = _make_conn(rows)
        with patch("routers.nudge.engine") as mock_engine:
            mock_engine.connect.return_value = mock_conn
            resp = await alfred_execute(req)
        assert resp.status == "success"
        assert "Call doctor" in resp.message
        assert "Buy groceries" in resp.message


# ─────────────────────────────────────────────────────
# add_reminder
# ─────────────────────────────────────────────────────

class TestAddReminder:
    @pytest.mark.asyncio
    async def test_without_title_returns_insufficient_data(self):
        req = _req("add_reminder")
        resp = await alfred_execute(req)
        assert resp.status == "error"
        assert resp.error_code == "INSUFFICIENT_DATA"

    @pytest.mark.asyncio
    async def test_with_title_parse_success(self):
        req = _req("add_reminder", {"title": "Call John tomorrow at 3pm"})
        mock_parse_result = {
            "reminder": {
                "title": "Call John",
                "body": "Call John",
                "type": "once",
                "fireAt": "2026-04-14T07:00:00Z",
                "cronExpression": None,
                "timezone": "Asia/Shanghai",
                "triggerSource": "whatsapp",
                "triggerCondition": None,
            },
            "confidence": 0.95,
            "rawInterpretation": "Call John tomorrow at 3pm",
        }
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("routers.nudge.parse_reminder", new=AsyncMock(return_value=mock_parse_result)), \
             patch("routers.nudge.engine") as mock_engine:
            mock_engine.connect.return_value = mock_conn
            resp = await alfred_execute(req)

        assert resp.status == "success"
        assert "Reminder set" in resp.message
        assert "Call John" in resp.message

    @pytest.mark.asyncio
    async def test_with_title_parse_fallback_still_creates_reminder(self):
        """When parse_reminder raises, the handler uses a fallback and still creates the reminder."""
        req = _req("add_reminder", {"title": "water plants"})
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("routers.nudge.parse_reminder", new=AsyncMock(side_effect=Exception("LLM unavailable"))), \
             patch("routers.nudge.engine") as mock_engine:
            mock_engine.connect.return_value = mock_conn
            resp = await alfred_execute(req)

        assert resp.status == "success"
        assert "water plants" in resp.message.lower() or "Reminder set" in resp.message
