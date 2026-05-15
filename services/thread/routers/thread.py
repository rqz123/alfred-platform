import sys
import os
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import pytz

_monorepo_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _monorepo_root not in sys.path:
    sys.path.insert(0, _monorepo_root)

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, insert, update, delete, func

from shared.auth import make_verify_token, TokenPayload
from database import engine, reminders, threads, thread_links
from models import (
    ParseRequest, ParseResponse, ParsedReminder,
    ReminderCreate, ReminderOut, ReminderUpdate,
    ThreadCreate, ThreadOut, ThreadUpdate,
)
from services.parser import parse_reminder, compute_next_fire

router = APIRouter()
verify_token = make_verify_token("/api/auth/login")


def _to_utc_iso(dt_str: str | None, tz_name: str = "UTC") -> str | None:
    """Normalize a possibly-local ISO datetime string to UTC for consistent storage."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            tz = pytz.timezone(tz_name)
            dt = tz.localize(dt)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return dt_str


# ─────────────────────────────────────────────────────
# Reminder REST endpoints (kept for backward compat)
# ─────────────────────────────────────────────────────

@router.post("/parse", response_model=ParseResponse)
async def parse(req: ParseRequest, _: TokenPayload = Depends(verify_token)):
    try:
        result = await parse_reminder(req.input, req.timezone)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI parse failed: {e}")
    return ParseResponse(
        reminder=ParsedReminder(**result["reminder"]),
        confidence=result["confidence"],
        rawInterpretation=result["rawInterpretation"],
    )


@router.post("/reminders", response_model=ReminderOut)
async def create_reminder(data: ReminderCreate, _: TokenPayload = Depends(verify_token)):
    now = datetime.now(timezone.utc).isoformat()
    reminder_id = str(uuid.uuid4())
    next_fire = None
    if data.cronExpression:
        next_fire = compute_next_fire(data.cronExpression, data.timezone)
    elif data.fireAt:
        next_fire = _to_utc_iso(data.fireAt, data.timezone)
    row = {
        "id": reminder_id,
        "title": data.title,
        "body": data.body,
        "type": data.type,
        "fireAt": _to_utc_iso(data.fireAt, data.timezone),
        "cronExpression": data.cronExpression,
        "timezone": data.timezone,
        "triggerSource": data.triggerSource,
        "triggerCondition": data.triggerCondition,
        "shortName": None,
        "status": "active",
        "lastFiredAt": None,
        "nextFireAt": next_fire,
        "createdAt": now,
        "updatedAt": now,
    }
    with engine.connect() as conn:
        conn.execute(insert(reminders).values(**row))
        conn.commit()
    return ReminderOut(**row)


@router.get("/reminders", response_model=list[ReminderOut])
async def list_reminders_rest(
    status: Optional[str] = None,
    type: Optional[str] = None,
    _: TokenPayload = Depends(verify_token),
):
    with engine.connect() as conn:
        rows = conn.execute(select(reminders).order_by(reminders.c.createdAt.desc())).mappings().all()
    result = [ReminderOut(**dict(r)) for r in rows]
    if status:
        result = [r for r in result if r.status == status]
    if type:
        result = [r for r in result if r.type == type]
    return result


@router.patch("/reminders/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    reminder_id: str,
    data: ReminderUpdate,
    _: TokenPayload = Depends(verify_token),
):
    now = datetime.now(timezone.utc).isoformat()
    with engine.connect() as conn:
        row = conn.execute(select(reminders).where(reminders.c.id == reminder_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Reminder not found")
        conn.execute(update(reminders).where(reminders.c.id == reminder_id).values(status=data.status, updatedAt=now))
        conn.commit()
        updated = conn.execute(select(reminders).where(reminders.c.id == reminder_id)).mappings().first()
    return ReminderOut(**dict(updated))


@router.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder(reminder_id: str, _: TokenPayload = Depends(verify_token)):
    with engine.connect() as conn:
        row = conn.execute(select(reminders).where(reminders.c.id == reminder_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Reminder not found")
        conn.execute(delete(reminders).where(reminders.c.id == reminder_id))
        conn.commit()


# ─────────────────────────────────────────────────────
# Thread REST endpoints
# ─────────────────────────────────────────────────────

def _parse_trigger_json(row) -> dict:
    """Extract trigger JSON from a DB row, handling both str and dict."""
    t = row.get("trigger") or {}
    if isinstance(t, str):
        try:
            t = json.loads(t) if t else {}
        except Exception:
            t = {}
    return t


def _build_thread_out(row, all_rows: list, all_links: list) -> ThreadOut:
    thread_id = row["id"]
    phone = row.get("triggerSource")

    explicit_ids: set[str] = set()
    for lnk in all_links:
        if lnk["thread_id"] == thread_id:
            explicit_ids.add(lnk["linked_thread_id"])
        elif lnk["linked_thread_id"] == thread_id:
            explicit_ids.add(lnk["thread_id"])

    ents = row.get("entities") or {}
    if isinstance(ents, str):
        try:
            ents = json.loads(ents)
        except Exception:
            ents = {}

    my_ents: set[str] = set()
    for v in ents.values():
        my_ents.update(v)

    entity_related_ids: set[str] = set()
    if my_ents and phone:
        for r in all_rows:
            if r["id"] == thread_id or r.get("triggerSource") != phone:
                continue
            r_ents = r.get("entities") or {}
            if isinstance(r_ents, str):
                try:
                    r_ents = json.loads(r_ents)
                except Exception:
                    r_ents = {}
            r_all: set[str] = set()
            for v in r_ents.values():
                r_all.update(v)
            if my_ents & r_all:
                entity_related_ids.add(r["id"])

    id_to_short = {r["id"]: r.get("shortId") for r in all_rows}
    all_related = explicit_ids | entity_related_ids
    related_short_ids = sorted(
        [sid for nid in all_related if (sid := id_to_short.get(nid)) is not None]
    )

    acl_raw = row.get("acl")
    if isinstance(acl_raw, str):
        try:
            acl_raw = json.loads(acl_raw)
        except Exception:
            acl_raw = None

    return ThreadOut(
        id=thread_id,
        shortId=row.get("shortId"),
        title=row.get("title"),
        content=row["content"],
        category=row.get("category"),
        tags=row.get("tags"),
        entities=ents if any(ents.values()) else None,
        relatedIds=related_short_ids or None,
        triggerSource=phone,
        trigger=_parse_trigger_json(row) or None,
        snoozeCount=row.get("snoozeCount", 0),
        source=row.get("source"),
        priority=row.get("priority"),
        status=row["status"],
        acl=acl_raw,
        createdAt=row["createdAt"],
        updatedAt=row["updatedAt"],
    )


@router.post("/threads", response_model=ThreadOut)
async def create_thread(data: ThreadCreate, _: TokenPayload = Depends(verify_token)):
    now = datetime.now(timezone.utc).isoformat()
    thread_id = str(uuid.uuid4())
    phone = data.triggerSource
    next_short_id: Optional[int] = None
    if phone:
        with engine.connect() as conn:
            max_sid = conn.execute(
                select(func.max(threads.c.shortId)).where(threads.c.triggerSource == phone)
            ).scalar()
        next_short_id = (max_sid or 0) + 1
    trigger = data.trigger or {"type": "none", "fire_at": None, "cron": None, "location": None, "ack_status": "pending", "ack_timeout_at": None}
    acl = data.acl or {"tier": "shared", "created_by": phone, "visible_to": []}
    if not acl.get("created_by"):
        acl["created_by"] = phone
    row = {
        "id": thread_id,
        "shortId": next_short_id,
        "title": None,
        "content": data.content,
        "category": data.category or "life",
        "tags": data.tags,
        "entities": None,
        "triggerSource": phone,
        "trigger": json.dumps(trigger),
        "acl": json.dumps(acl),
        "snoozeCount": 0,
        "source": getattr(data, "source", None) or "web",
        "priority": getattr(data, "priority", None),
        "status": "active",
        "createdAt": now,
        "updatedAt": now,
    }
    with engine.connect() as conn:
        conn.execute(insert(threads).values(**row))
        conn.commit()
    out = {**row, "trigger": trigger, "acl": acl}
    return ThreadOut(**{k: v for k, v in out.items() if k in ThreadOut.model_fields})


@router.get("/threads", response_model=list[ThreadOut])
async def list_threads_endpoint(
    status: Optional[str] = None,
    _: TokenPayload = Depends(verify_token),
):
    with engine.connect() as conn:
        all_rows = conn.execute(select(threads).order_by(threads.c.createdAt.desc())).mappings().all()
        all_lnks = conn.execute(select(thread_links)).mappings().all()
    result = [_build_thread_out(r, all_rows, all_lnks) for r in all_rows]
    if status:
        result = [n for n in result if n.status == status]
    return result


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, _: TokenPayload = Depends(verify_token)):
    with engine.connect() as conn:
        row = conn.execute(select(threads).where(threads.c.id == thread_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        conn.execute(delete(threads).where(threads.c.id == thread_id))
        conn.commit()


class SnoozeTriggerRequest(BaseModel):
    minutes: int = 30


@router.post("/threads/{thread_id}/snooze")
async def snooze_thread_endpoint(
    thread_id: str,
    data: SnoozeTriggerRequest,
    _: TokenPayload = Depends(verify_token),
):
    with engine.connect() as conn:
        row = conn.execute(select(threads).where(threads.c.id == thread_id)).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    t = _parse_trigger_json(row)
    if not t or t.get("type") == "none":
        raise HTTPException(status_code=400, detail="Thread has no trigger")
    if data.minutes <= 0:
        raise HTTPException(status_code=422, detail="minutes must be a positive integer")
    if t.get("ack_status") not in ("pending", "awaiting"):
        raise HTTPException(status_code=409, detail=f"Cannot snooze a trigger with status '{t.get('ack_status')}'")
    now_dt = datetime.now(timezone.utc)
    new_fire_at = (now_dt + timedelta(minutes=data.minutes)).isoformat()
    updated_trigger = {**t, "fire_at": new_fire_at, "ack_status": "pending"}
    snooze_count = int(row.get("snoozeCount") or 0)
    with engine.connect() as conn:
        conn.execute(
            update(threads).where(threads.c.id == thread_id).values(
                trigger=json.dumps(updated_trigger),
                snoozeCount=snooze_count + 1,
                updatedAt=now_dt.isoformat(),
            )
        )
        conn.commit()
    return {"ok": True, "fire_at": new_fire_at}


@router.post("/threads/{thread_id}/dismiss")
async def dismiss_thread_endpoint(
    thread_id: str,
    _: TokenPayload = Depends(verify_token),
):
    with engine.connect() as conn:
        row = conn.execute(select(threads).where(threads.c.id == thread_id)).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    t = _parse_trigger_json(row)
    if not t or t.get("type") == "none":
        raise HTTPException(status_code=400, detail="Thread has no trigger")
    if t.get("ack_status") not in ("pending", "awaiting"):
        raise HTTPException(status_code=409, detail=f"Cannot dismiss a trigger with status '{t.get('ack_status')}'")
    updated_trigger = {**t, "ack_status": "dismissed"}
    now = datetime.now(timezone.utc).isoformat()
    with engine.connect() as conn:
        conn.execute(
            update(threads).where(threads.c.id == thread_id).values(
                trigger=json.dumps(updated_trigger),
                status="sleeping",
                updatedAt=now,
            )
        )
        conn.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────
# Brain-facing endpoints (API-key auth, not JWT)
# ─────────────────────────────────────────────────────

class TriggerStatusUpdate(BaseModel):
    expected_status: str        # CAS: only update if current ack_status matches this
    new_status: str             # target ack_status
    ack_timeout_at: Optional[str] = None   # set when transitioning to awaiting
    fire_at: Optional[str] = None          # set when rescheduling recurring


def _thread_trigger_summary(r, t: dict) -> dict:
    acl_raw = r.get("acl")
    if isinstance(acl_raw, str):
        try:
            acl_raw = json.loads(acl_raw)
        except Exception:
            acl_raw = {}
    acl_tier = (acl_raw or {}).get("tier", "shared")
    return {
        "thread_id": r["id"],
        "short_id": r.get("shortId"),
        "content": r["content"],
        "category": r.get("category"),
        "trigger_source": r.get("triggerSource"),
        "trigger": t,
        "family_id": None,
        "acl_tier": acl_tier,
    }


# API key auth used by Brain-facing endpoints (defined here so it's available before first use)
_ALFRED_API_KEY = (
    os.environ.get("THREAD_API_KEY", "")
    or os.environ.get("NUDGE_API_KEY", "")
    or os.environ.get("ALFRED_API_KEY", "")
)
_DEFAULT_TZ = (
    os.environ.get("THREAD_DEFAULT_TIMEZONE", "")
    or os.environ.get("NUDGE_DEFAULT_TIMEZONE", "America/Los_Angeles")
)


def _verify_alfred_key(x_alfred_api_key: str | None = Header(default=None)) -> None:
    if not _ALFRED_API_KEY or x_alfred_api_key != _ALFRED_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Alfred API key")


@router.get("/triggers/pending", dependencies=[Depends(_verify_alfred_key)])
async def get_pending_triggers(lookahead_minutes: int = 5):
    """Return threads whose trigger fire_at is within the next N minutes (Brain polling)."""
    now = datetime.now(timezone.utc)
    cutoff = (now + timedelta(minutes=lookahead_minutes)).isoformat()
    with engine.connect() as conn:
        rows = conn.execute(
            select(threads).where(
                threads.c.trigger.isnot(None),
                threads.c.status == "active",
            )
        ).mappings().all()

    results = []
    for r in rows:
        t = _parse_trigger_json(r)
        if not t or t.get("type") == "none":
            continue
        if t.get("ack_status") != "pending" or not t.get("fire_at"):
            continue
        if t["fire_at"] <= cutoff:
            results.append(_thread_trigger_summary(r, t))
    return results


@router.get("/triggers/awaiting", dependencies=[Depends(_verify_alfred_key)])
async def get_awaiting_triggers():
    """Return threads in awaiting state (Brain polls to detect ack timeouts)."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(threads).where(
                threads.c.trigger.isnot(None),
                threads.c.status == "active",
            )
        ).mappings().all()

    results = []
    for r in rows:
        t = _parse_trigger_json(r)
        if not t or t.get("type") == "none":
            continue
        if t.get("ack_status") == "awaiting":
            results.append(_thread_trigger_summary(r, t))
    return results


@router.patch("/threads/{thread_id}/trigger-status", dependencies=[Depends(_verify_alfred_key)])
async def update_trigger_status(thread_id: str, data: TriggerStatusUpdate):
    """Atomic CAS update of trigger.ack_status. Returns 409 if current status does not match expected."""
    now = datetime.now(timezone.utc).isoformat()
    with engine.connect() as conn:
        row = conn.execute(select(threads).where(threads.c.id == thread_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Thread not found")

        current_trigger = _parse_trigger_json(row)
        current_status = current_trigger.get("ack_status", "pending")

        if current_status != data.expected_status:
            raise HTTPException(
                status_code=409,
                detail=f"CAS conflict: expected {data.expected_status!r} but found {current_status!r}",
            )

        current_trigger["ack_status"] = data.new_status
        if data.ack_timeout_at is not None:
            current_trigger["ack_timeout_at"] = data.ack_timeout_at
        if data.fire_at is not None:
            current_trigger["fire_at"] = data.fire_at

        conn.execute(
            update(threads)
            .where(threads.c.id == thread_id)
            .values(trigger=json.dumps(current_trigger), updatedAt=now)
        )
        conn.commit()

    return {"thread_id": thread_id, "ack_status": data.new_status}


@router.get("/alfred/threads", dependencies=[Depends(_verify_alfred_key)])
async def list_alfred_threads(user_phone: str):
    """Return active threads for a given user_phone. Brain uses this for proactive nudge scanning."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(threads).where(
                threads.c.triggerSource == user_phone,
                threads.c.status == "active",
            )
        ).mappings().all()
    return [
        {
            "id": r["id"],
            "title": r.get("title"),
            "content": r.get("content", ""),
            "createdAt": r.get("createdAt"),
            "updatedAt": r.get("updatedAt"),
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────
# ASI (Alfred Service Interface) endpoints
# ─────────────────────────────────────────────────────

def _next_short_id(conn, phone: str) -> int:
    max_sid = conn.execute(
        select(func.max(threads.c.shortId)).where(threads.c.triggerSource == phone)
    ).scalar()
    return (max_sid or 0) + 1


@router.delete("/alfred/admin/clear", status_code=204, dependencies=[Depends(_verify_alfred_key)])
async def admin_clear_threads():
    """Clear all threads and legacy reminders (dev/test only)."""
    with engine.connect() as conn:
        conn.execute(delete(thread_links))
        conn.execute(delete(threads))
        conn.execute(delete(reminders))
        conn.commit()


class AlfredExecuteRequest(BaseModel):
    request_id: str
    user_id: str
    whatsapp_id: str
    intent: str
    entities: dict[str, Any] = {}
    session: dict = {}
    timestamp: str = ""


class AlfredExecuteResponse(BaseModel):
    request_id: str
    status: str
    message: str = ""
    data: Optional[Any] = None
    error_code: Optional[str] = None
    quick_replies: list[str] = []


@router.get("/health")
def health():
    return {"service": "thread", "status": "ok", "version": "1.0.0"}


@router.get("/alfred/capabilities", dependencies=[Depends(_verify_alfred_key)])
def capabilities():
    return {
        "service": "thread",
        "display_name": "Thread Skill",
        "capabilities": [
            {
                "intent": "add_reminder",
                "description": "Add a reminder (creates a Thread with trigger)",
                "required_entities": [{"name": "title", "type": "string", "prompt": "What should I remind you about?"}],
                "optional_entities": [{"name": "date", "type": "date", "prompt": "When should I remind you?"}],
            },
            {"intent": "list_reminders", "description": "List active reminders"},
            {"intent": "get_schedule", "description": "View today's schedule"},
            {"intent": "cancel_reminder", "description": "Cancel a reminder by number or name"},
            {"intent": "acknowledge_reminder", "description": "Acknowledge a waiting reminder"},
            {"intent": "snooze_thread", "description": "Delay a reminder by N minutes"},
            {"intent": "dismiss_thread", "description": "Permanently dismiss a reminder"},
            {"intent": "add_thread", "description": "Save a thread or memory"},
            {"intent": "list_threads", "description": "List recent threads"},
            {"intent": "search_threads", "description": "Search threads by topic"},
            {"intent": "thread_get", "description": "Get a thread by number"},
            {"intent": "thread_delete", "description": "Delete a thread by number"},
            {"intent": "thread_link", "description": "Link two threads"},
            {"intent": "thread_unlink", "description": "Unlink two threads"},
            {"intent": "thread_links", "description": "List all links for a thread"},
        ],
    }


def _day_utc_bounds(date_entity: str):
    tz = pytz.timezone(_DEFAULT_TZ)
    now_local = datetime.now(tz)
    if date_entity == "tomorrow":
        target = (now_local + timedelta(days=1)).date()
    elif date_entity == "yesterday":
        target = (now_local - timedelta(days=1)).date()
    else:
        target = now_local.date()
    day_start_local = tz.localize(datetime(target.year, target.month, target.day, 0, 0, 0))
    day_end_local = day_start_local + timedelta(days=1)
    day_start_utc = day_start_local.astimezone(timezone.utc)
    day_end_utc = day_end_local.astimezone(timezone.utc)
    return target, day_start_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00"), day_end_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _fmt_utc_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(pytz.timezone(_DEFAULT_TZ))
        return local.strftime("%H:%M")
    except Exception:
        return iso


def _fmt_local(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(pytz.timezone(_DEFAULT_TZ))
        return local.strftime("%-m/%-d at %-I:%M %p %Z")
    except Exception:
        return iso


@router.post("/alfred/execute", response_model=AlfredExecuteResponse, dependencies=[Depends(_verify_alfred_key)])
async def alfred_execute(req: AlfredExecuteRequest):

    # ── list_reminders ────────────────────────────────────────────────
    if req.intent == "list_reminders":
        phone = req.whatsapp_id
        with engine.connect() as conn:
            rows = conn.execute(
                select(threads).where(
                    threads.c.triggerSource == phone,
                    threads.c.trigger.isnot(None),
                    threads.c.status == "active",
                )
            ).mappings().all()
        due = []
        for r in rows:
            t = _parse_trigger_json(r)
            if not t or t.get("type") == "none":
                continue
            if t.get("ack_status") in ("dismissed", "acknowledged", "expired"):
                continue
            due.append((r, t))
        due.sort(key=lambda x: x[1].get("fire_at") or "")
        if not due:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="You have no pending reminders.",
            )
        lines = []
        for r, t in due:
            fire = _fmt_local(t["fire_at"]) if t.get("fire_at") else "TBD"
            title = r.get("title") or r.get("content", "")[:40]
            lines.append(f"#{r.get('shortId')}: {title} @ {fire}")
        lines.append('\nTo cancel, say "cancel reminder #N"')
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message="Your reminders:\n" + "\n".join(lines),
        )

    # ── get_schedule ─────────────────────────────────────────────────
    if req.intent == "get_schedule":
        date_entity = req.entities.get("date", "today")
        target_date, start_iso, end_iso = _day_utc_bounds(date_entity)
        phone = req.whatsapp_id
        with engine.connect() as conn:
            rows = conn.execute(
                select(threads).where(
                    threads.c.triggerSource == phone,
                    threads.c.trigger.isnot(None),
                    threads.c.status == "active",
                )
            ).mappings().all()
        due = []
        for r in rows:
            t = _parse_trigger_json(r)
            if not t or t.get("type") == "none":
                continue
            fire_at = t.get("fire_at")
            if not fire_at or not (start_iso <= fire_at < end_iso):
                continue
            due.append((r, t))
        due.sort(key=lambda x: x[1].get("fire_at") or "")
        label = {"today": "Today", "tomorrow": "Tomorrow", "yesterday": "Yesterday"}.get(date_entity, "Today")
        if not due:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message=f"No reminders scheduled for {label.lower()} ({target_date}).",
            )
        lines = [
            f"#{r.get('shortId')}: {r.get('title') or r.get('content','')[:40]} @ {_fmt_utc_time(t['fire_at'])}"
            for r, t in due
        ]
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"{label}'s schedule ({target_date}):\n" + "\n".join(lines),
        )

    # ── cancel_reminder ──────────────────────────────────────────────
    if req.intent == "cancel_reminder":
        ref = (req.entities.get("ref") or req.entities.get("title") or "").strip()
        if not ref:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message='Which reminder should I cancel? Say the number, e.g. "cancel reminder 1".',
            )
        phone = req.whatsapp_id
        with engine.connect() as conn:
            user_rows = conn.execute(
                select(threads).where(
                    threads.c.triggerSource == phone,
                    threads.c.status == "active",
                    threads.c.trigger.isnot(None),
                ).order_by(threads.c.createdAt)
            ).mappings().all()
        matched_row = None
        matched_trigger = None
        ref_lower = ref.lower().lstrip("#")
        # If ref ends in digits (e.g. "提醒1", "reminder3"), extract as shortId candidate
        _m_sid = re.search(r'(\d+)$', ref_lower)
        ref_as_sid = _m_sid.group(1) if _m_sid else ref_lower
        # Word set for partial name matching (e.g. "meeting" matches "meet friends")
        ref_words = set(re.findall(r'\w+', ref_lower))
        for row in user_rows:
            t = _parse_trigger_json(row)
            if not t or t.get("type") == "none":
                continue
            if t.get("ack_status") in ("dismissed", "acknowledged"):
                continue
            sid = str(row.get("shortId") or "")
            title = (row.get("title") or row.get("content", ""))[:80].lower()
            title_words = set(re.findall(r'\w+', title))
            if (ref_as_sid == sid
                    or ref_lower in title
                    or (len(ref_words) >= 1 and ref_words & title_words)):
                matched_row = row
                matched_trigger = t
                break
        if matched_row is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message=f'I couldn\'t find a reminder matching "{ref}". Say "list reminders" to see yours.',
            )
        now = datetime.now(timezone.utc).isoformat()
        updated_trigger = {**matched_trigger, "ack_status": "dismissed"}
        new_status = "sleeping" if matched_trigger.get("type") == "once" else "active"
        with engine.connect() as conn:
            conn.execute(
                update(threads).where(threads.c.id == matched_row["id"]).values(
                    trigger=json.dumps(updated_trigger), status=new_status, updatedAt=now,
                )
            )
            conn.commit()
        title = matched_row.get("title") or matched_row.get("content", "")[:40]
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"Cancelled Thread #{matched_row.get('shortId')}: {title}",
        )

    # ── add_reminder ─────────────────────────────────────────────────
    if req.intent == "add_reminder":
        title = req.entities.get("title", "")
        if not title:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="Please tell me what to remind you about, e.g.: remind me to call John tomorrow",
            )
        # time_hint carries the raw follow-up text (e.g. "tomorrow at noon")
        # so the parser sees the full phrase, not just the extracted date keyword.
        time_hint = (req.entities.get("time_hint") or "").strip()
        date_hint = (req.entities.get("date") or "").strip()
        if time_hint and time_hint.lower() not in title.lower():
            parse_input = f"{title} {time_hint}"
        elif date_hint and date_hint.lower() not in title.lower():
            parse_input = f"{title} {date_hint}"
        else:
            parse_input = title
        try:
            result = await parse_reminder(parse_input, _DEFAULT_TZ)
        except Exception:
            result = {
                "reminder": {"title": title, "type": "once", "fireAt": None, "cronExpression": None,
                             "timezone": _DEFAULT_TZ, "triggerSource": "whatsapp", "triggerCondition": None, "body": title},
                "confidence": 0.5, "rawInterpretation": title,
            }
        parsed = result["reminder"]
        fire_at = parsed.get("fireAt")
        cron = parsed.get("cronExpression")
        if not fire_at and not cron:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message='When should I remind you? Please include a time, e.g. "tomorrow at 9am" or "every Monday at 8am".',
            )
        phone = req.whatsapp_id
        now = datetime.now(timezone.utc).isoformat()
        tz_name = parsed.get("timezone", _DEFAULT_TZ)
        fire_at_utc = _to_utc_iso(fire_at, tz_name)
        next_fire = compute_next_fire(cron, tz_name) if cron else fire_at_utc
        trigger_type = "recurring" if cron else "once"
        trigger = {
            "type": trigger_type, "fire_at": next_fire, "cron": cron,
            "location": None, "ack_status": "pending", "ack_timeout_at": None,
        }
        thread_title = parsed.get("title", title)
        acl_reminder = {"tier": "shared", "created_by": phone, "visible_to": []}
        with engine.connect() as conn:
            next_sid = _next_short_id(conn, phone)
            thread_id = str(uuid.uuid4())
            conn.execute(insert(threads).values(
                id=thread_id, shortId=next_sid,
                title=thread_title, content=thread_title,
                category="routine", trigger=json.dumps(trigger),
                acl=json.dumps(acl_reminder),
                snoozeCount=0, source="whatsapp",
                triggerSource=phone, status="active",
                createdAt=now, updatedAt=now,
            ))
            conn.commit()
        if next_fire:
            fire_display = _fmt_local(next_fire)
        elif cron:
            fire_display = f"recurring ({cron})"
        else:
            fire_display = "TBD"
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"Thread #{next_sid} set: {thread_title}\nAt: {fire_display}",
            data={
                "thread_id": thread_id,
                "short_id": next_sid,
                "category": "routine",
                "trigger": trigger,
                "trigger_type": trigger_type,
                "acl_tier": acl_reminder["tier"],
            },
        )

    # ── acknowledge_reminder ─────────────────────────────────────────
    if req.intent == "acknowledge_reminder":
        phone = req.whatsapp_id
        with engine.connect() as conn:
            all_active = conn.execute(
                select(threads).where(
                    threads.c.triggerSource == phone,
                    threads.c.status == "active",
                    threads.c.trigger.isnot(None),
                )
            ).mappings().all()
        awaiting = [(r, t) for r in all_active if (t := _parse_trigger_json(r)) and t.get("ack_status") == "awaiting"]
        if not awaiting:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="No reminders are waiting for confirmation.",
            )
        now = datetime.now(timezone.utc).isoformat()
        confirmed = []
        for row, t in awaiting:
            cron = t.get("cron")
            if cron:
                next_fire = compute_next_fire(cron, _DEFAULT_TZ)
                updated_trigger = {**t, "ack_status": "pending", "fire_at": next_fire}
                new_status = "active"
            else:
                updated_trigger = {**t, "ack_status": "acknowledged"}
                new_status = "sleeping"
            with engine.connect() as conn:
                conn.execute(
                    update(threads).where(threads.c.id == row["id"]).values(
                        trigger=json.dumps(updated_trigger), status=new_status, updatedAt=now,
                    )
                )
                conn.commit()
            title = row.get("title") or row.get("content", "")[:40]
            confirmed.append(f"#{row.get('shortId')}: {title}")
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message="✓ Got it! Confirmed:\n" + "\n".join(confirmed),
        )

    # ── snooze_thread ────────────────────────────────────────────────
    if req.intent == "snooze_thread":
        phone = req.whatsapp_id
        ref = str(req.entities.get("short_id") or req.entities.get("ref") or "").strip().lstrip("#")
        delay_minutes = int(req.entities.get("delay_minutes") or 30)
        with engine.connect() as conn:
            user_rows = conn.execute(
                select(threads).where(
                    threads.c.triggerSource == phone,
                    threads.c.status == "active",
                    threads.c.trigger.isnot(None),
                )
            ).mappings().all()
        matched_row = None
        matched_trigger = None
        for row in user_rows:
            t = _parse_trigger_json(row)
            if not t or t.get("type") == "none":
                continue
            sid = str(row.get("shortId") or "")
            if ref and ref == sid:
                matched_row = row
                matched_trigger = t
                break
            if not matched_row and t.get("ack_status") == "awaiting":
                matched_row = row
                matched_trigger = t
        if matched_row is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message="No reminder found to snooze. Say 'list reminders' to see yours.",
            )
        now_dt = datetime.now(timezone.utc)
        new_fire_at = (now_dt + timedelta(minutes=delay_minutes)).isoformat()
        updated_trigger = {**matched_trigger, "fire_at": new_fire_at, "ack_status": "pending"}
        current_snooze = int(matched_row.get("snoozeCount") or 0)
        with engine.connect() as conn:
            conn.execute(
                update(threads).where(threads.c.id == matched_row["id"]).values(
                    trigger=json.dumps(updated_trigger),
                    snoozeCount=current_snooze + 1,
                    updatedAt=now_dt.isoformat(),
                )
            )
            conn.commit()
        title = matched_row.get("title") or matched_row.get("content", "")[:40]
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"Snoozed! Thread #{matched_row.get('shortId')} will remind you in {delay_minutes} minutes.",
        )

    # ── dismiss_thread ───────────────────────────────────────────────
    if req.intent == "dismiss_thread":
        phone = req.whatsapp_id
        ref = str(req.entities.get("short_id") or req.entities.get("ref") or "").strip().lstrip("#")
        with engine.connect() as conn:
            user_rows = conn.execute(
                select(threads).where(
                    threads.c.triggerSource == phone,
                    threads.c.status == "active",
                    threads.c.trigger.isnot(None),
                )
            ).mappings().all()
        matched_row = None
        matched_trigger = None
        for row in user_rows:
            t = _parse_trigger_json(row)
            if not t or t.get("type") == "none":
                continue
            sid = str(row.get("shortId") or "")
            if ref and ref == sid:
                matched_row = row
                matched_trigger = t
                break
            if not matched_row and t.get("ack_status") == "awaiting":
                matched_row = row
                matched_trigger = t
        if matched_row is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message="No reminder found to dismiss.",
            )
        now = datetime.now(timezone.utc).isoformat()
        updated_trigger = {**matched_trigger, "ack_status": "dismissed"}
        with engine.connect() as conn:
            conn.execute(
                update(threads).where(threads.c.id == matched_row["id"]).values(
                    trigger=json.dumps(updated_trigger), status="sleeping", updatedAt=now,
                )
            )
            conn.commit()
        title = matched_row.get("title") or matched_row.get("content", "")[:40]
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"Got it — Thread #{matched_row.get('shortId')} won't bother you again.",
        )

    # ── add_thread ───────────────────────────────────────────────────
    if req.intent == "add_thread":
        content = (req.entities.get("content") or "").strip()
        if not content:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="What would you like to save as a thread?",
            )
        phone = req.whatsapp_id
        thread_entities: dict = {"people": [], "places": [], "orgs": []}
        thread_title = ""
        category = "life"
        try:
            from services.parser import get_client
            client = get_client()
            ent_resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            'Analyze this thread. Return JSON with:\n'
                            '- "title": very brief title (max 8 words or 10 Chinese chars, no quotes)\n'
                            '- "category": one of "pro" (work/professional), "life" (daily life/health/family), '
                            '"emo" (emotions/relationships), "routine" (habits/recurring tasks)\n'
                            '- "people": array of person names explicitly mentioned\n'
                            '- "places": array of places explicitly mentioned\n'
                            '- "orgs": array of organizations explicitly mentioned\n'
                            'Example: {"title": "王医生复诊血压正常", "category": "life", '
                            '"people": ["王医生"], "places": [], "orgs": []}'
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                response_format={"type": "json_object"},
                max_tokens=150,
                timeout=8.0,
            )
            extracted = json.loads(ent_resp.choices[0].message.content)
            thread_entities = {
                "people": extracted.get("people", []),
                "places": extracted.get("places", []),
                "orgs": extracted.get("orgs", []),
            }
            thread_title = (extracted.get("title") or "").strip()
            raw_cat = (extracted.get("category") or "life").lower()
            if raw_cat in ("pro", "life", "emo", "routine"):
                category = raw_cat
        except Exception:
            pass

        intent_vector: dict = {"urgency": 0.5, "social_bond": 0.5, "goal_alignment": 0.5}
        try:
            from services.parser import get_client as _get_client
            _iv_client = _get_client()
            _iv_resp = await _iv_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Score this message on three dimensions (0.0-1.0 each), return JSON:\n"
                            '{"urgency": float, "social_bond": float, "goal_alignment": float}\n'
                            "urgency: how time-sensitive (0=not urgent, 1=very urgent)\n"
                            "social_bond: how much it relates to relationships (0=none, 1=high)\n"
                            "goal_alignment: alignment with long-term family goals (0=none, 1=high); default 0.5"
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                response_format={"type": "json_object"},
                max_tokens=60,
                timeout=5.0,
            )
            _iv_raw = json.loads(_iv_resp.choices[0].message.content)
            intent_vector = {
                k: max(0.0, min(1.0, float(_iv_raw.get(k, 0.5))))
                for k in ("urgency", "social_bond", "goal_alignment")
            }
        except Exception:
            pass

        now = datetime.now(timezone.utc).isoformat()
        thread_id = str(uuid.uuid4())
        trigger = {"type": "none", "fire_at": None, "cron": None, "location": None, "ack_status": "pending", "ack_timeout_at": None}
        acl = {"tier": "shared", "created_by": phone, "visible_to": []}
        with engine.connect() as conn:
            next_sid = _next_short_id(conn, phone)
            conn.execute(insert(threads).values(
                id=thread_id, shortId=next_sid,
                title=thread_title or None, content=content,
                category=category, tags=None,
                entities=json.dumps(thread_entities),
                triggerSource=phone,
                trigger=json.dumps(trigger),
                acl=json.dumps(acl),
                snoozeCount=0, source="whatsapp",
                status="active", createdAt=now, updatedAt=now,
            ))
            conn.commit()

        preview = content[:50] + ("…" if len(content) > 50 else "")
        reply = f"✏️ Thread #{next_sid}: {preview}"

        all_ents = (
            thread_entities.get("people", []) +
            thread_entities.get("places", []) +
            thread_entities.get("orgs", [])
        )
        if all_ents:
            with engine.connect() as conn:
                past_rows = conn.execute(
                    select(threads)
                    .where(
                        threads.c.status == "active",
                        threads.c.triggerSource == phone,
                        threads.c.id != thread_id,
                    )
                    .order_by(threads.c.createdAt.desc())
                    .limit(30)
                ).mappings().all()
            related = []
            for r in past_rows:
                r_ents = r.get("entities") or {}
                if isinstance(r_ents, str):
                    try:
                        r_ents = json.loads(r_ents)
                    except Exception:
                        r_ents = {}
                r_all = r_ents.get("people", []) + r_ents.get("places", []) + r_ents.get("orgs", [])
                if any(e in r_all for e in all_ents):
                    related.append(r)
                    if len(related) >= 3:
                        break
            if related:
                entity_label = all_ents[0]
                for e in all_ents:
                    for r in related:
                        r_ents = r.get("entities") or {}
                        if isinstance(r_ents, str):
                            try:
                                r_ents = json.loads(r_ents)
                            except Exception:
                                r_ents = {}
                        if e in (r_ents.get("people", []) + r_ents.get("places", []) + r_ents.get("orgs", [])):
                            entity_label = e
                            break
                tz_local = pytz.timezone(_DEFAULT_TZ)
                history_lines = []
                for r in related:
                    try:
                        dt = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        date_str = dt.astimezone(tz_local).strftime("%-m/%-d")
                    except Exception:
                        date_str = "?"
                    snippet = r["content"][:60] + ("…" if len(r["content"]) > 60 else "")
                    sid_str = f"#{r.get('shortId')} " if r.get("shortId") else ""
                    history_lines.append(f"  • {date_str}: {sid_str}{snippet}")
                reply += (
                    f"\n\n📋 About 「{entity_label}」 — {len(related)} related thread(s):\n"
                    + "\n".join(history_lines)
                )

        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=reply,
            data={
                "thread_id": thread_id,
                "short_id": next_sid,
                "category": category,
                "trigger": trigger,
                "intent_vector": intent_vector,
                "acl_tier": acl["tier"],
            },
        )

    # ── list_threads ─────────────────────────────────────────────────
    if req.intent == "list_threads":
        phone = req.whatsapp_id
        limit = min(int(req.entities.get("limit") or 10), 20)
        with engine.connect() as conn:
            rows = conn.execute(
                select(threads)
                .where(threads.c.status == "active", threads.c.triggerSource == phone)
                .order_by(threads.c.createdAt.desc())
                .limit(limit)
            ).mappings().all()
        if not rows:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="You haven't recorded any threads yet.",
            )
        tz = pytz.timezone(_DEFAULT_TZ)
        lines = []
        for r in rows:
            try:
                dt = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                date_str = dt.astimezone(tz).strftime("%-m/%-d")
            except Exception:
                date_str = ""
            sid_str = f"#{r.get('shortId')} " if r.get("shortId") else ""
            preview = r["content"][:55] + ("…" if len(r["content"]) > 55 else "")
            lines.append(f"  {sid_str}{preview} ({date_str})")
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"Your {len(rows)} thread(s):\n" + "\n".join(lines),
        )

    # ── search_threads ───────────────────────────────────────────────
    if req.intent == "search_threads":
        query = (req.entities.get("query") or req.entities.get("content") or "").strip()
        if not query:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="What would you like to search for in your threads?",
            )
        phone = req.whatsapp_id
        with engine.connect() as conn:
            rows = conn.execute(
                select(threads)
                .where(threads.c.status == "active", threads.c.triggerSource == phone)
                .order_by(threads.c.createdAt.desc())
            ).mappings().all()
        if not rows:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="You have no threads to search.",
            )
        threads_text = "\n".join(f"{i}. {r['content']}" for i, r in enumerate(rows, 1))
        try:
            from services.parser import get_client
            client = get_client()
            ai_resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a personal assistant helping search through the user's threads. "
                            "Find the most relevant threads and summarize what you found. "
                            "Be concise (under 200 words). If nothing is relevant, say so clearly."
                        ),
                    },
                    {"role": "user", "content": f"My threads:\n{threads_text}\n\nSearch query: {query}"},
                ],
                max_tokens=300,
                timeout=15.0,
            )
            answer = ai_resp.choices[0].message.content.strip()
        except Exception:
            matches = [r for r in rows if query.lower() in r["content"].lower()]
            if not matches:
                answer = f'No threads found matching "{query}".'
            else:
                answer = f"Found {len(matches)} matching thread(s):\n" + "\n".join(
                    f"- {r['content'][:80]}" for r in matches[:5]
                )
        return AlfredExecuteResponse(request_id=req.request_id, status="success", message=answer)

    # ── thread_get ───────────────────────────────────────────────────
    if req.intent == "thread_get":
        short_id = req.entities.get("short_id")
        if short_id is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message="Which thread? Usage: /thread get #<id>",
            )
        phone = req.whatsapp_id
        with engine.connect() as conn:
            row = conn.execute(
                select(threads).where(
                    threads.c.shortId == int(short_id),
                    threads.c.triggerSource == phone,
                    threads.c.status == "active",
                )
            ).mappings().first()
        if row is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message=f"Thread #{short_id} not found.",
            )
        try:
            dt = datetime.fromisoformat(row["createdAt"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            date_str = dt.astimezone(pytz.timezone(_DEFAULT_TZ)).strftime("%-m/%-d at %-I:%M %p %Z")
        except Exception:
            date_str = row["createdAt"]
        ents = row.get("entities") or {}
        if isinstance(ents, str):
            try:
                ents = json.loads(ents)
            except Exception:
                ents = {}
        ent_parts = [", ".join(v) for v in ents.values() if v]
        msg = f"📝 Thread #{short_id} [{date_str}]\n{row['content']}"
        if ent_parts:
            msg += "\n🔑 " + " · ".join(ent_parts)
        return AlfredExecuteResponse(request_id=req.request_id, status="success", message=msg)

    # ── thread_delete ────────────────────────────────────────────────
    if req.intent == "thread_delete":
        short_id = req.entities.get("short_id")
        title_query = (req.entities.get("title") or "").strip().lower()

        if short_id is None and not title_query:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message="Which thread? Say 'delete thread #<id>' or 'delete thread <name>'.",
            )
        phone = req.whatsapp_id
        row = None
        with engine.connect() as conn:
            if short_id is not None:
                row = conn.execute(
                    select(threads).where(
                        threads.c.shortId == int(short_id),
                        threads.c.triggerSource == phone,
                    )
                ).mappings().first()
            else:
                all_rows = conn.execute(
                    select(threads).where(
                        threads.c.triggerSource == phone,
                        threads.c.status == "active",
                    )
                ).mappings().all()
                row = next((
                    r for r in all_rows
                    if title_query in (r.get("title") or "").lower()
                    or title_query in (r.get("content") or "").lower()
                ), None)
        if row is None:
            ref = f"#{short_id}" if short_id is not None else repr(title_query)
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message=f"Thread {ref} not found.",
            )
        display_sid = row.get("shortId", short_id)
        if not req.entities.get("confirmed"):
            preview = (row["content"] or "")[:80]
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message=f"🗑 Delete Thread #{display_sid}?\n\"{preview}\"\n\nReply yes to confirm.",
            )
        with engine.connect() as conn:
            conn.execute(delete(threads).where(threads.c.id == row["id"]))
            conn.commit()
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"✅ Thread #{display_sid} deleted.",
        )

    # ── thread_link ──────────────────────────────────────────────────
    if req.intent == "thread_link":
        thread_a = req.entities.get("thread_a")
        thread_b = req.entities.get("thread_b")
        if not thread_a or not thread_b:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Usage: /link #<id_A> #<id_B>")
        if int(thread_a) == int(thread_b):
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Cannot link a thread to itself.")
        phone = req.whatsapp_id
        with engine.connect() as conn:
            row_a = conn.execute(select(threads).where(threads.c.shortId == int(thread_a), threads.c.triggerSource == phone)).mappings().first()
            row_b = conn.execute(select(threads).where(threads.c.shortId == int(thread_b), threads.c.triggerSource == phone)).mappings().first()
        if not row_a:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message=f"Thread #{thread_a} not found.")
        if not row_b:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message=f"Thread #{thread_b} not found.")
        with engine.connect() as conn:
            existing = conn.execute(select(thread_links).where(
                ((thread_links.c.thread_id == row_a["id"]) & (thread_links.c.linked_thread_id == row_b["id"])) |
                ((thread_links.c.thread_id == row_b["id"]) & (thread_links.c.linked_thread_id == row_a["id"]))
            )).first()
            if not existing:
                conn.execute(insert(thread_links).values(
                    id=str(uuid.uuid4()),
                    thread_id=row_a["id"],
                    linked_thread_id=row_b["id"],
                    created_by=phone,
                    createdAt=datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"🔗 Linked #{thread_a} and #{thread_b}.",
        )

    # ── thread_unlink ────────────────────────────────────────────────
    if req.intent == "thread_unlink":
        thread_a = req.entities.get("thread_a")
        thread_b = req.entities.get("thread_b")
        if not thread_a or not thread_b:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Usage: /unlink #<id_A> #<id_B>")
        phone = req.whatsapp_id
        with engine.connect() as conn:
            row_a = conn.execute(select(threads).where(threads.c.shortId == int(thread_a), threads.c.triggerSource == phone)).mappings().first()
            row_b = conn.execute(select(threads).where(threads.c.shortId == int(thread_b), threads.c.triggerSource == phone)).mappings().first()
        if not row_a or not row_b:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="One or both threads not found.")
        with engine.connect() as conn:
            conn.execute(delete(thread_links).where(
                ((thread_links.c.thread_id == row_a["id"]) & (thread_links.c.linked_thread_id == row_b["id"])) |
                ((thread_links.c.thread_id == row_b["id"]) & (thread_links.c.linked_thread_id == row_a["id"]))
            ))
            conn.commit()
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"✂️ Link removed between #{thread_a} and #{thread_b}.",
        )

    # ── thread_links ─────────────────────────────────────────────────
    if req.intent == "thread_links":
        short_id = req.entities.get("short_id")
        if not short_id:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Usage: /thread links #<id>")
        phone = req.whatsapp_id
        with engine.connect() as conn:
            target = conn.execute(select(threads).where(
                threads.c.shortId == int(short_id), threads.c.triggerSource == phone
            )).mappings().first()
        if not target:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message=f"Thread #{short_id} not found.")
        with engine.connect() as conn:
            lnks = conn.execute(select(thread_links).where(
                (thread_links.c.thread_id == target["id"]) | (thread_links.c.linked_thread_id == target["id"])
            )).mappings().all()
        linked_ids = [
            lnk["linked_thread_id"] if lnk["thread_id"] == target["id"] else lnk["thread_id"]
            for lnk in lnks
        ]
        explicit_shorts: list[tuple] = []
        if linked_ids:
            with engine.connect() as conn:
                exp_rows = conn.execute(select(threads).where(threads.c.id.in_(linked_ids))).mappings().all()
            explicit_shorts = [(r.get("shortId"), r["content"][:50]) for r in exp_rows]
        tgt_ents = target.get("entities") or {}
        if isinstance(tgt_ents, str):
            try:
                tgt_ents = json.loads(tgt_ents)
            except Exception:
                tgt_ents = {}
        my_ents: set = set()
        for v in tgt_ents.values():
            my_ents.update(v)
        entity_shorts: list[tuple] = []
        if my_ents:
            with engine.connect() as conn:
                past = conn.execute(select(threads).where(
                    threads.c.triggerSource == phone,
                    threads.c.id != target["id"],
                    threads.c.status == "active",
                )).mappings().all()
            for r in past:
                r_ents = r.get("entities") or {}
                if isinstance(r_ents, str):
                    try:
                        r_ents = json.loads(r_ents)
                    except Exception:
                        r_ents = {}
                r_all: set = set()
                for v in r_ents.values():
                    r_all.update(v)
                if my_ents & r_all:
                    entity_shorts.append((r.get("shortId"), r["content"][:50]))
        lines: list[str] = []
        if explicit_shorts:
            lines.append("🔗 Explicit links:")
            for sid, snip in explicit_shorts:
                lines.append(f"  #{sid}: {snip}")
        if entity_shorts:
            lines.append("🧠 Entity-related:")
            for sid, snip in entity_shorts[:5]:
                lines.append(f"  #{sid}: {snip}")
        if not lines:
            return AlfredExecuteResponse(request_id=req.request_id, status="success", message=f"Thread #{short_id} has no related threads.")
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"Thread #{short_id} connections:\n" + "\n".join(lines),
        )

    return AlfredExecuteResponse(
        request_id=req.request_id, status="error",
        error_code="NOT_FOUND", message="Unknown intent",
    )
