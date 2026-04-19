import sys
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import pytz

# Add monorepo root to path for local dev so `shared` package is importable
# In Docker, shared is installed as a package so this is a no-op
_monorepo_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _monorepo_root not in sys.path:
    sys.path.insert(0, _monorepo_root)

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, insert, update, delete

from shared.auth import make_verify_token, TokenPayload
from database import engine, reminders, notes
from models import (
    ParseRequest, ParseResponse, ParsedReminder,
    ReminderCreate, ReminderOut, ReminderUpdate,
    NoteCreate, NoteOut, NoteUpdate,
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

    short_name = _assign_pet_name(_taken_names(data.triggerSource))

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
        "shortName": short_name,
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
async def list_reminders(
    status: Optional[str] = None,
    type: Optional[str] = None,
    _: TokenPayload = Depends(verify_token),
):
    with engine.connect() as conn:
        query = select(reminders).order_by(reminders.c.createdAt.desc())
        rows = conn.execute(query).mappings().all()

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
        conn.execute(
            update(reminders)
            .where(reminders.c.id == reminder_id)
            .values(status=data.status, updatedAt=now)
        )
        conn.commit()
        updated = conn.execute(select(reminders).where(reminders.c.id == reminder_id)).mappings().first()
    return ReminderOut(**dict(updated))


@router.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder(
    reminder_id: str,
    _: TokenPayload = Depends(verify_token),
):
    with engine.connect() as conn:
        row = conn.execute(select(reminders).where(reminders.c.id == reminder_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Reminder not found")
        conn.execute(delete(reminders).where(reminders.c.id == reminder_id))
        conn.commit()


# ─────────────────────────────────────────────────────
# Note REST endpoints
# ─────────────────────────────────────────────────────

@router.post("/notes", response_model=NoteOut)
async def create_note(data: NoteCreate, _: TokenPayload = Depends(verify_token)):
    now = datetime.now(timezone.utc).isoformat()
    note_id = str(uuid.uuid4())
    row = {
        "id": note_id,
        "content": data.content,
        "tags": data.tags,
        "triggerSource": data.triggerSource,
        "status": "active",
        "createdAt": now,
        "updatedAt": now,
    }
    with engine.connect() as conn:
        conn.execute(insert(notes).values(**row))
        conn.commit()
    return NoteOut(**row)


@router.get("/notes", response_model=list[NoteOut])
async def list_notes_endpoint(
    status: Optional[str] = None,
    _: TokenPayload = Depends(verify_token),
):
    with engine.connect() as conn:
        query = select(notes).order_by(notes.c.createdAt.desc())
        rows = conn.execute(query).mappings().all()
    result = [NoteOut(**dict(r)) for r in rows]
    if status:
        result = [n for n in result if n.status == status]
    return result


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    _: TokenPayload = Depends(verify_token),
):
    with engine.connect() as conn:
        row = conn.execute(select(notes).where(notes.c.id == note_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Note not found")
        conn.execute(delete(notes).where(notes.c.id == note_id))
        conn.commit()


# ─────────────────────────────────────────────────────
# ASI (Alfred Service Interface) endpoints
# ─────────────────────────────────────────────────────

_ALFRED_API_KEY = os.environ.get("NUDGE_API_KEY", "") or os.environ.get("ALFRED_API_KEY", "")
_DEFAULT_TZ = os.environ.get("NUDGE_DEFAULT_TIMEZONE", "America/Los_Angeles")

# Cute pet names assigned to reminders so users can reference them easily.
# Names are unique per-user across active+paused reminders.
_PET_NAMES = [
    "Biscuit", "Mochi", "Coco", "Luna", "Bella", "Daisy", "Poppy", "Waffles",
    "Peanut", "Nugget", "Pudding", "Snickers", "Toffee", "Maple", "Pretzel",
    "Cocoa", "Noodle", "Dumpling", "Boba", "Latte", "Chai", "Oreo", "Pickles",
    "Sushi", "Tofu", "Miso", "Ramen", "Ginger", "Pepper", "Cheddar", "Nacho",
    "Churro", "Brownie", "Caramel", "Truffle", "Marshmallow", "Butterscotch",
    "Fudge", "Jellybean", "Sprinkles", "Cupcake", "Cookie", "Muffin", "Wafer",
    "Taffy", "Gumdrop", "Pumpkin", "Cobbler", "Doughnut", "Éclair",
]


def _assign_pet_name(exclude: set[str]) -> str:
    """Pick a pet name not already in use. Falls back to Name+N if all taken."""
    import random
    available = [n for n in _PET_NAMES if n not in exclude]
    if available:
        return random.choice(available)
    # All 50 names taken — append a number
    i = 2
    base = random.choice(_PET_NAMES)
    while f"{base}{i}" in exclude:
        i += 1
    return f"{base}{i}"


def _taken_names(phone: str | None = None) -> set[str]:
    """Return set of shortNames already in use (active or paused) for the given phone."""
    with engine.connect() as conn:
        q = select(reminders.c.shortName).where(
            reminders.c.status.in_(["active", "paused"]),
            reminders.c.shortName.isnot(None),
        )
        if phone:
            q = q.where(reminders.c.triggerSource == phone)
        rows = conn.execute(q).all()
    return {r[0] for r in rows if r[0]}


def _verify_alfred_key(x_alfred_api_key: str | None = Header(default=None)) -> None:
    if not _ALFRED_API_KEY or x_alfred_api_key != _ALFRED_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Alfred API key")


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
    return {"service": "nudge", "status": "ok", "version": "1.0.0"}


@router.get("/alfred/capabilities", dependencies=[Depends(_verify_alfred_key)])
def capabilities():
    return {
        "service": "nudge",
        "display_name": "Nudge Reminder Assistant",
        "capabilities": [
            {
                "intent": "add_reminder",
                "description": "Add a reminder",
                "required_entities": [{"name": "title", "type": "string", "prompt": "What should I remind you about?"}],
                "optional_entities": [{"name": "date", "type": "date", "prompt": "When should I remind you?"}],
            },
            {"intent": "list_reminders", "description": "List active reminders"},
            {"intent": "get_schedule", "description": "View today's schedule"},
            {"intent": "add_note", "description": "Save a note or memory"},
            {"intent": "list_notes", "description": "List recent notes"},
            {"intent": "search_notes", "description": "Search notes by topic"},
        ],
    }


def _day_utc_bounds(date_entity: str):
    """Return (target_date, start_iso, end_iso) UTC strings for the target date in the default timezone."""
    tz = pytz.timezone(_DEFAULT_TZ)
    now_local = datetime.now(tz)
    if date_entity == "tomorrow":
        target = (now_local + timedelta(days=1)).date()
    elif date_entity == "yesterday":
        target = (now_local - timedelta(days=1)).date()
    else:
        target = now_local.date()
    # Midnight in local timezone → convert to UTC
    day_start_local = tz.localize(datetime(target.year, target.month, target.day, 0, 0, 0))
    day_end_local = day_start_local + timedelta(days=1)
    day_start_utc = day_start_local.astimezone(timezone.utc)
    day_end_utc = day_end_local.astimezone(timezone.utc)
    return target, day_start_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00"), day_end_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _fmt_utc_time(iso: str) -> str:
    """Convert a UTC ISO string to local time HH:MM for display."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        tz = pytz.timezone(_DEFAULT_TZ)
        local = dt.astimezone(tz)
        return local.strftime("%H:%M")
    except Exception:
        return iso


def _fmt_local(iso: str) -> str:
    """Convert a UTC ISO string to a friendly local date+time string, e.g. 'Apr 19 at 11:02 PM PDT'."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        tz = pytz.timezone(_DEFAULT_TZ)
        local = dt.astimezone(tz)
        return local.strftime("%-m/%-d at %-I:%M %p %Z")
    except Exception:
        return iso


@router.post("/alfred/execute", response_model=AlfredExecuteResponse, dependencies=[Depends(_verify_alfred_key)])
async def alfred_execute(req: AlfredExecuteRequest):
    if req.intent == "list_reminders":
        with engine.connect() as conn:
            rows = conn.execute(
                select(reminders)
                .where(reminders.c.status == "active")
                .order_by(reminders.c.nextFireAt)
                .limit(5)
            ).mappings().all()
        if not rows:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="You have no pending reminders.",
            )
        lines = []
        for r in rows:
            fire_raw = r.get("nextFireAt") or r.get("fireAt")
            fire = _fmt_local(fire_raw) if fire_raw else "TBD"
            pet = r.get("shortName") or "?"
            lines.append(f"\U0001f43e {pet}: {r['title']} @ {fire}")
        lines.append('\nTo cancel, say "cancel Mochi" or "cancel [pet name]"')
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message="Your reminders:\n" + "\n".join(lines),
        )

    if req.intent == "get_schedule":
        date_entity = req.entities.get("date", "today")
        target_date, start_iso, end_iso = _day_utc_bounds(date_entity)

        with engine.connect() as conn:
            rows = conn.execute(
                select(reminders).where(
                    reminders.c.status == "active",
                    reminders.c.nextFireAt >= start_iso,
                    reminders.c.nextFireAt < end_iso,
                ).order_by(reminders.c.nextFireAt)
            ).mappings().all()

        label = {"today": "Today", "tomorrow": "Tomorrow", "yesterday": "Yesterday"}.get(
            date_entity, "Today"
        )
        if not rows:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message=f"No reminders scheduled for {label.lower()} ({target_date}).",
            )
        lines = [
            f"\U0001f43e {r['shortName'] or '?'}: {r['title']} @ {_fmt_utc_time(r['nextFireAt'])}"
            for r in rows
        ]
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"{label}'s schedule ({target_date}):\n" + "\n".join(lines),
        )

    if req.intent == "cancel_reminder":
        ref = (req.entities.get("ref") or req.entities.get("title") or "").strip()
        if not ref:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="Which reminder should I cancel? Say the number or name, e.g. \"cancel reminder 1\" or \"cancel Alarm\".",
            )
        # Fetch active reminders for this user ordered by creation time
        phone = req.whatsapp_id
        with engine.connect() as conn:
            user_rows = conn.execute(
                select(reminders)
                .where(
                    reminders.c.status == "active",
                    reminders.c.triggerSource == phone,
                )
                .order_by(reminders.c.createdAt)
            ).mappings().all()

        matched_id = None
        matched_title = None
        matched_pet = None
        ref_lower = ref.lower()
        for row in user_rows:
            pet = (row.get("shortName") or "").lower()
            title = (row.get("title") or "").lower()
            if ref_lower == pet or ref_lower in pet or ref_lower in title:
                matched_id = row["id"]
                matched_title = row["title"]
                matched_pet = row.get("shortName")
                break

        if matched_id is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message=f'I couldn\'t find a reminder called "{ref}". Say "list reminders" to see yours.',
            )

        now = datetime.now(timezone.utc).isoformat()
        with engine.connect() as conn:
            conn.execute(
                update(reminders).where(reminders.c.id == matched_id).values(status="done", updatedAt=now)
            )
            conn.commit()

        label = f"\U0001f43e {matched_pet}" if matched_pet else matched_title
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"Cancelled {label}: {matched_title}",
        )

    if req.intent == "add_reminder":
        title = req.entities.get("title", "")
        if not title:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="Please tell me what to remind you about, e.g.: remind me to call John tomorrow",
            )
        # Parse and create reminder using the existing parse service
        try:
            result = await parse_reminder(title, _DEFAULT_TZ)
        except Exception:
            result = {"reminder": {"title": title, "type": "once", "fireAt": None,
                                   "cronExpression": None, "timezone": _DEFAULT_TZ,
                                   "triggerSource": "whatsapp", "triggerCondition": None,
                                   "body": title},
                      "confidence": 0.5, "rawInterpretation": title}

        now = datetime.now(timezone.utc).isoformat()
        reminder_id = str(uuid.uuid4())
        parsed = result["reminder"]
        fire_at = parsed.get("fireAt")
        cron = parsed.get("cronExpression")
        tz_name = parsed.get("timezone", _DEFAULT_TZ)
        fire_at_utc = _to_utc_iso(fire_at, tz_name)
        next_fire = compute_next_fire(cron, tz_name) if cron else fire_at_utc

        short_name = _assign_pet_name(_taken_names(req.whatsapp_id))
        row = {
            "id": reminder_id,
            "title": parsed.get("title", title),
            "body": parsed.get("body", title),
            "type": parsed.get("type", "once"),
            "fireAt": fire_at_utc,
            "cronExpression": cron,
            "timezone": parsed.get("timezone", _DEFAULT_TZ),
            "triggerSource": req.whatsapp_id,
            "triggerCondition": parsed.get("triggerCondition"),
            "shortName": short_name,
            "status": "active",
            "lastFiredAt": None,
            "nextFireAt": next_fire,
            "createdAt": now,
            "updatedAt": now,
        }
        with engine.connect() as conn:
            conn.execute(insert(reminders).values(**row))
            conn.commit()

        fire_display = _fmt_local(next_fire) if next_fire else "TBD"
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"Reminder set \U0001f43e {short_name}: {row['title']}\nAt: {fire_display}",
        )

    if req.intent == "add_note":
        content = (req.entities.get("content") or "").strip()
        if not content:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="What would you like me to note down?",
            )
        now = datetime.now(timezone.utc).isoformat()
        note_id = str(uuid.uuid4())
        row = {
            "id": note_id,
            "content": content,
            "tags": None,
            "triggerSource": req.whatsapp_id,
            "status": "active",
            "createdAt": now,
            "updatedAt": now,
        }
        with engine.connect() as conn:
            conn.execute(insert(notes).values(**row))
            conn.commit()
        preview = content[:50] + ("…" if len(content) > 50 else "")
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"\u270f\ufe0f Noted: {preview}",
        )

    if req.intent == "list_notes":
        phone = req.whatsapp_id
        with engine.connect() as conn:
            rows = conn.execute(
                select(notes)
                .where(notes.c.status == "active", notes.c.triggerSource == phone)
                .order_by(notes.c.createdAt.desc())
                .limit(10)
            ).mappings().all()
        if not rows:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="You haven't recorded any notes yet.",
            )
        tz = pytz.timezone(_DEFAULT_TZ)
        lines = []
        for i, r in enumerate(rows, 1):
            try:
                dt = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                date_str = dt.astimezone(tz).strftime("%-m/%-d")
            except Exception:
                date_str = ""
            preview = r["content"][:60] + ("…" if len(r["content"]) > 60 else "")
            lines.append(f"{i}. {preview} ({date_str})")
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message="Your notes:\n" + "\n".join(lines),
        )

    if req.intent == "search_notes":
        query = (req.entities.get("query") or req.entities.get("content") or "").strip()
        if not query:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="What would you like to search for in your notes?",
            )
        phone = req.whatsapp_id
        with engine.connect() as conn:
            rows = conn.execute(
                select(notes)
                .where(notes.c.status == "active", notes.c.triggerSource == phone)
                .order_by(notes.c.createdAt.desc())
            ).mappings().all()
        if not rows:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="You have no notes to search.",
            )
        # Use GPT to find relevant notes
        notes_text = "\n".join(
            f"{i}. {r['content']}" for i, r in enumerate(rows, 1)
        )
        try:
            from services.parser import get_client
            client = get_client()
            ai_resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a personal assistant helping search through the user's notes. "
                            "Given the notes list and a search query, find the most relevant notes "
                            "and summarize what you found. Be concise (under 200 words). "
                            "If nothing is relevant, say so clearly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"My notes:\n{notes_text}\n\nSearch query: {query}",
                    },
                ],
                max_tokens=300,
                timeout=15.0,
            )
            answer = ai_resp.choices[0].message.content.strip()
        except Exception:
            # Fallback: simple substring search
            matches = [r for r in rows if query.lower() in r["content"].lower()]
            if not matches:
                answer = f'No notes found matching "{query}".'
            else:
                lines = [f"- {r['content'][:80]}" for r in matches[:5]]
                answer = f"Found {len(matches)} matching note(s):\n" + "\n".join(lines)
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=answer,
        )

    return AlfredExecuteResponse(
        request_id=req.request_id, status="error",
        error_code="NOT_FOUND", message="Unknown intent",
    )
