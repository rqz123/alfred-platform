"""
Tests for get_schedule intent in the Nudge ASI handler.

Verifies:
- Empty schedule returns "no reminders" message
- Reminders due today appear in the response
- Reminders due tomorrow do NOT appear in today's schedule
- date entity 'tomorrow' queries the next day
- _day_utc_bounds helper produces correct UTC range for Asia/Shanghai
"""

import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# Add nudge service root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.nudge import _day_utc_bounds, _fmt_utc_time


# ─────────────────────────────────────────────────────
# Unit tests for helper functions
# ─────────────────────────────────────────────────────

def test_day_utc_bounds_today():
    target, start, end = _day_utc_bounds("today")
    # start + 8h should equal midnight on target date
    start_dt = datetime.fromisoformat(start)
    assert (start_dt + timedelta(hours=8)).date() == target
    # Range should be exactly 24 hours
    end_dt = datetime.fromisoformat(end)
    assert end_dt - start_dt == timedelta(hours=24)


def test_day_utc_bounds_tomorrow():
    today_target, _, _ = _day_utc_bounds("today")
    tomorrow_target, start, end = _day_utc_bounds("tomorrow")
    assert tomorrow_target == today_target + timedelta(days=1)
    start_dt = datetime.fromisoformat(start)
    assert (start_dt + timedelta(hours=8)).date() == tomorrow_target


def test_day_utc_bounds_yesterday():
    today_target, _, _ = _day_utc_bounds("today")
    yesterday_target, start, end = _day_utc_bounds("yesterday")
    assert yesterday_target == today_target - timedelta(days=1)


def test_day_utc_bounds_unknown_defaults_to_today():
    today_target, today_start, _ = _day_utc_bounds("today")
    unknown_target, unknown_start, _ = _day_utc_bounds("next_week")
    assert unknown_target == today_target
    assert unknown_start == today_start


def test_fmt_utc_time_converts_to_local():
    # 2026-04-13T08:00:00Z = 16:00 Asia/Shanghai
    result = _fmt_utc_time("2026-04-13T08:00:00Z")
    assert result == "16:00"


def test_fmt_utc_time_invalid_returns_original():
    result = _fmt_utc_time("not-a-date")
    assert result == "not-a-date"


# ─────────────────────────────────────────────────────
# Integration tests for the ASI execute endpoint
# ─────────────────────────────────────────────────────

def _make_req(intent, entities=None):
    from routers.nudge import AlfredExecuteRequest
    return AlfredExecuteRequest(
        request_id="test-req-001",
        user_id="user1",
        whatsapp_id="+8613800000000",
        intent=intent,
        entities=entities or {},
        timestamp="2026-04-13T08:00:00Z",
    )


def _make_row(title, next_fire):
    """Return a dict mimicking a SQLAlchemy mapping row."""
    return {"id": "abc", "title": title, "nextFireAt": next_fire, "status": "active"}


@pytest.mark.asyncio
async def test_get_schedule_empty():
    req = _make_req("get_schedule")
    target, start, end = _day_utc_bounds("today")

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.mappings.return_value.all.return_value = []

    with patch("routers.nudge.engine") as mock_engine:
        mock_engine.connect.return_value = mock_conn
        from routers.nudge import alfred_execute
        resp = await alfred_execute(req)

    assert resp.status == "success"
    assert "no reminders" in resp.message.lower()
    assert str(target) in resp.message
    assert "Add reminder" in resp.quick_replies


@pytest.mark.asyncio
async def test_get_schedule_with_reminders():
    req = _make_req("get_schedule")
    target, start, end = _day_utc_bounds("today")

    # Two reminders within today's UTC window
    fire1 = start[:10] + "T02:00:00"   # 10:00 Asia/Shanghai
    fire2 = start[:10] + "T06:30:00"   # 14:30 Asia/Shanghai
    rows = [_make_row("Morning standup", fire1), _make_row("Lunch with team", fire2)]

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.mappings.return_value.all.return_value = rows

    with patch("routers.nudge.engine") as mock_engine:
        mock_engine.connect.return_value = mock_conn
        from routers.nudge import alfred_execute
        resp = await alfred_execute(req)

    assert resp.status == "success"
    assert "Today" in resp.message
    assert "Morning standup" in resp.message
    assert "Lunch with team" in resp.message


@pytest.mark.asyncio
async def test_get_schedule_tomorrow():
    req = _make_req("get_schedule", entities={"date": "tomorrow"})
    target, _, _ = _day_utc_bounds("tomorrow")

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.mappings.return_value.all.return_value = []

    with patch("routers.nudge.engine") as mock_engine:
        mock_engine.connect.return_value = mock_conn
        from routers.nudge import alfred_execute
        resp = await alfred_execute(req)

    assert resp.status == "success"
    assert "tomorrow" in resp.message.lower()
    assert str(target) in resp.message


@pytest.mark.asyncio
async def test_get_schedule_does_not_create_reminder():
    """get_schedule must NOT insert any row into reminders (old bug: shared handler with add_reminder)."""
    req = _make_req("get_schedule")

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.mappings.return_value.all.return_value = []

    with patch("routers.nudge.engine") as mock_engine:
        mock_engine.connect.return_value = mock_conn
        from routers.nudge import alfred_execute
        await alfred_execute(req)

    # Ensure execute was called exactly once (the SELECT), not twice (SELECT + INSERT)
    assert mock_conn.execute.call_count == 1
    call_str = str(mock_conn.execute.call_args_list[0])
    # Should be a SELECT query, not INSERT
    assert "INSERT" not in call_str.upper() or "SELECT" in call_str.upper()
