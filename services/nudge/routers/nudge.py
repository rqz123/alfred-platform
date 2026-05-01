import sys
import os
import json
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
from sqlalchemy import select, insert, update, delete, func

from shared.auth import make_verify_token, TokenPayload
from database import engine, reminders, notes, note_links
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

def _build_note_out(row, all_rows: list, all_links: list) -> NoteOut:
    """Build NoteOut with shortId, title, entities, and computed relatedIds."""
    note_id = row["id"]
    phone = row.get("triggerSource")

    explicit_ids: set[str] = set()
    for lnk in all_links:
        if lnk["note_id"] == note_id:
            explicit_ids.add(lnk["linked_note_id"])
        elif lnk["linked_note_id"] == note_id:
            explicit_ids.add(lnk["note_id"])

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
            if r["id"] == note_id or r.get("triggerSource") != phone:
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

    return NoteOut(
        id=note_id,
        shortId=row.get("shortId"),
        title=row.get("title"),
        content=row["content"],
        tags=row.get("tags"),
        entities=ents if any(ents.values()) else None,
        relatedIds=related_short_ids or None,
        triggerSource=phone,
        status=row["status"],
        createdAt=row["createdAt"],
        updatedAt=row["updatedAt"],
    )


@router.post("/notes", response_model=NoteOut)
async def create_note(data: NoteCreate, _: TokenPayload = Depends(verify_token)):
    now = datetime.now(timezone.utc).isoformat()
    note_id = str(uuid.uuid4())
    phone = data.triggerSource
    next_short_id: Optional[int] = None
    if phone:
        with engine.connect() as conn:
            max_sid = conn.execute(
                select(func.max(notes.c.shortId)).where(notes.c.triggerSource == phone)
            ).scalar()
        next_short_id = (max_sid or 0) + 1
    row = {
        "id": note_id,
        "shortId": next_short_id,
        "title": None,
        "content": data.content,
        "tags": data.tags,
        "entities": None,
        "triggerSource": phone,
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
        all_rows = conn.execute(select(notes).order_by(notes.c.createdAt.desc())).mappings().all()
        all_lnks = conn.execute(select(note_links)).mappings().all()
    result = [_build_note_out(r, all_rows, all_lnks) for r in all_rows]
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


@router.delete("/alfred/admin/clear", status_code=204, dependencies=[Depends(_verify_alfred_key)])
async def admin_clear_notes():
    """Clear all notes and reminders."""
    with engine.connect() as conn:
        conn.execute(delete(notes))
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
        # If the gateway also extracted a date entity separately, append it so the
        # parser has both subject and timing even if the title was stripped of the date.
        date_hint = (req.entities.get("date") or "").strip()
        parse_input = title
        if date_hint and date_hint.lower() not in title.lower():
            parse_input = f"{title} {date_hint}"

        # Parse and create reminder using the existing parse service
        try:
            result = await parse_reminder(parse_input, _DEFAULT_TZ)
        except Exception:
            result = {"reminder": {"title": title, "type": "once", "fireAt": None,
                                   "cronExpression": None, "timezone": _DEFAULT_TZ,
                                   "triggerSource": "whatsapp", "triggerCondition": None,
                                   "body": title},
                      "confidence": 0.5, "rawInterpretation": title}

        parsed = result["reminder"]
        fire_at = parsed.get("fireAt")
        cron = parsed.get("cronExpression")

        # Reject if no time was specified — a reminder without a time is useless
        if not fire_at and not cron:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="When should I remind you? Please include a time, e.g. \"tomorrow at 9am\" or \"every Monday at 8am\".",
            )

        now = datetime.now(timezone.utc).isoformat()
        reminder_id = str(uuid.uuid4())
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

    if req.intent == "acknowledge_reminder":
        phone = req.whatsapp_id
        with engine.connect() as conn:
            awaiting_rows = conn.execute(
                select(reminders).where(
                    reminders.c.status == "awaiting",
                    reminders.c.triggerSource == phone,
                )
            ).mappings().all()

        if not awaiting_rows:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="No reminders are waiting for confirmation.",
            )

        now = datetime.now(timezone.utc).isoformat()
        confirmed = []
        for r in awaiting_rows:
            if r.get("cronExpression"):
                next_fire = compute_next_fire(r["cronExpression"], r.get("timezone", _DEFAULT_TZ))
                upd = dict(status="active", nextFireAt=next_fire, ackRetries="0", updatedAt=now)
            else:
                upd = dict(status="done", nextFireAt=None, ackRetries="0", updatedAt=now)
            with engine.connect() as conn:
                conn.execute(update(reminders).where(reminders.c.id == r["id"]).values(**upd))
                conn.commit()
            pet = r.get("shortName")
            confirmed.append(f"\U0001f43e {pet}: {r['title']}" if pet else r["title"])

        names = "\n".join(confirmed)
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"\u2713 Got it! Confirmed:\n{names}",
        )

    if req.intent == "add_note":
        content = (req.entities.get("content") or "").strip()
        if not content:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="What would you like me to note down?",
            )

        phone = req.whatsapp_id

        # Assign per-user short ID
        with engine.connect() as conn:
            max_sid = conn.execute(
                select(func.max(notes.c.shortId)).where(notes.c.triggerSource == phone)
            ).scalar()
        next_short_id = (max_sid or 0) + 1

        # Extract entities + generate title via LLM — best-effort, single call
        note_entities: dict = {"people": [], "places": [], "orgs": []}
        note_title = ""
        try:
            from services.parser import get_client
            client = get_client()
            ent_resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            'Analyze this note. Return JSON with:\n'
                            '- "title": very brief title (max 8 words or 10 Chinese chars, no quotes or punctuation)\n'
                            '- "people": array of person names explicitly mentioned\n'
                            '- "places": array of places explicitly mentioned\n'
                            '- "orgs": array of organizations explicitly mentioned\n'
                            'Use empty arrays if none. Example: '
                            '{"title": "王医生复诊血压正常", "people": ["王医生"], "places": [], "orgs": []}'
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                response_format={"type": "json_object"},
                max_tokens=150,
                timeout=8.0,
            )
            extracted = json.loads(ent_resp.choices[0].message.content)
            note_entities = {
                "people": extracted.get("people", []),
                "places": extracted.get("places", []),
                "orgs":   extracted.get("orgs", []),
            }
            note_title = (extracted.get("title") or "").strip()
        except Exception:
            pass

        now = datetime.now(timezone.utc).isoformat()
        note_id = str(uuid.uuid4())
        row = {
            "id": note_id,
            "shortId": next_short_id,
            "title": note_title or None,
            "content": content,
            "tags": None,
            "entities": note_entities,
            "triggerSource": phone,
            "status": "active",
            "createdAt": now,
            "updatedAt": now,
        }
        with engine.connect() as conn:
            conn.execute(insert(notes).values(**row))
            conn.commit()

        preview = content[:50] + ("…" if len(content) > 50 else "")
        reply = f"\u270f\ufe0f Note #{next_short_id}: {preview}"

        # Entity correlation: surface related historical notes
        all_ents = (
            note_entities.get("people", []) +
            note_entities.get("places", []) +
            note_entities.get("orgs", [])
        )
        if all_ents:
            with engine.connect() as conn:
                past_rows = conn.execute(
                    select(notes)
                    .where(
                        notes.c.status == "active",
                        notes.c.triggerSource == phone,
                        notes.c.id != note_id,
                    )
                    .order_by(notes.c.createdAt.desc())
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
                    sid = r.get("shortId")
                    sid_str = f"#{sid} " if sid else ""
                    history_lines.append(f"  • {date_str}: {sid_str}{snippet}")

                reply += (
                    f"\n\n\U0001f4cb About \u300c{entity_label}\u300d"
                    f" — {len(related)} related note(s):\n"
                    + "\n".join(history_lines)
                )

        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=reply,
        )
    if req.intent == "list_notes":
        phone = req.whatsapp_id
        limit = min(int(req.entities.get("limit") or 10), 20)
        with engine.connect() as conn:
            rows = conn.execute(
                select(notes)
                .where(notes.c.status == "active", notes.c.triggerSource == phone)
                .order_by(notes.c.createdAt.desc())
                .limit(limit)
            ).mappings().all()
        if not rows:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="success",
                message="You haven't recorded any notes yet.",
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
            sid = r.get("shortId")
            sid_str = f"#{sid} " if sid else ""
            content_val = r["content"]
            preview = content_val[:55] + ("…" if len(content_val) > 55 else "")
            lines.append(f"  {sid_str}{preview} ({date_str})")
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=("Your {} note(s):\n".format(len(rows)) + "\n".join(lines)),
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


    if req.intent == "note_get":
        short_id = req.entities.get("short_id")
        if short_id is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message="Which note? Usage: /note get #<id>",
            )
        phone = req.whatsapp_id
        with engine.connect() as conn:
            row = conn.execute(
                select(notes).where(
                    notes.c.shortId == int(short_id),
                    notes.c.triggerSource == phone,
                    notes.c.status == "active",
                )
            ).mappings().first()
        if row is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message=f"Note #{short_id} not found.",
            )
        tz_local = pytz.timezone(_DEFAULT_TZ)
        try:
            dt = datetime.fromisoformat(row["createdAt"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            date_str = dt.astimezone(tz_local).strftime("%-m/%-d at %-I:%M %p %Z")
        except Exception:
            date_str = row["createdAt"]
        ents = row.get("entities") or {}
        if isinstance(ents, str):
            try:
                ents = json.loads(ents)
            except Exception:
                ents = {}
        ent_parts = [", ".join(v) for v in ents.values() if v]
        msg = "\U0001f4dd Note #{} [{}]\n{}".format(short_id, date_str, row['content'])
        if ent_parts:
            msg += "\n\U0001f511 {}".format(" \u00b7 ".join(ent_parts))
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=msg,
        )

    if req.intent == "note_delete":
        short_id = req.entities.get("short_id")
        if short_id is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message="Which note? Usage: /note delete #<id>",
            )
        phone = req.whatsapp_id
        with engine.connect() as conn:
            row = conn.execute(
                select(notes).where(
                    notes.c.shortId == int(short_id),
                    notes.c.triggerSource == phone,
                )
            ).mappings().first()
        if row is None:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                message=f"Note #{short_id} not found.",
            )
        with engine.connect() as conn:
            conn.execute(delete(notes).where(notes.c.id == row["id"]))
            conn.commit()
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"✅ Note #{short_id} deleted.",
        )

    if req.intent == "note_link":
        note_a = req.entities.get("note_a")
        note_b = req.entities.get("note_b")
        if not note_a or not note_b:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Usage: /link #<id_A> #<id_B>")
        if int(note_a) == int(note_b):
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Cannot link a note to itself.")
        phone = req.whatsapp_id
        with engine.connect() as conn:
            row_a = conn.execute(select(notes).where(notes.c.shortId == int(note_a), notes.c.triggerSource == phone)).mappings().first()
            row_b = conn.execute(select(notes).where(notes.c.shortId == int(note_b), notes.c.triggerSource == phone)).mappings().first()
        if not row_a:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message=f"Note #{note_a} not found.")
        if not row_b:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message=f"Note #{note_b} not found.")
        with engine.connect() as conn:
            existing = conn.execute(select(note_links).where(
                ((note_links.c.note_id == row_a["id"]) & (note_links.c.linked_note_id == row_b["id"])) |
                ((note_links.c.note_id == row_b["id"]) & (note_links.c.linked_note_id == row_a["id"]))
            )).first()
            if not existing:
                conn.execute(insert(note_links).values(
                    id=str(uuid.uuid4()),
                    note_id=row_a["id"],
                    linked_note_id=row_b["id"],
                    created_by=phone,
                    createdAt=datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message="\U0001f517 Linked #{} and #{}.".format(note_a, note_b),
        )

    if req.intent == "note_unlink":
        note_a = req.entities.get("note_a")
        note_b = req.entities.get("note_b")
        if not note_a or not note_b:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Usage: /unlink #<id_A> #<id_B>")
        phone = req.whatsapp_id
        with engine.connect() as conn:
            row_a = conn.execute(select(notes).where(notes.c.shortId == int(note_a), notes.c.triggerSource == phone)).mappings().first()
            row_b = conn.execute(select(notes).where(notes.c.shortId == int(note_b), notes.c.triggerSource == phone)).mappings().first()
        if not row_a or not row_b:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="One or both notes not found.")
        with engine.connect() as conn:
            conn.execute(delete(note_links).where(
                ((note_links.c.note_id == row_a["id"]) & (note_links.c.linked_note_id == row_b["id"])) |
                ((note_links.c.note_id == row_b["id"]) & (note_links.c.linked_note_id == row_a["id"]))
            ))
            conn.commit()
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message="✂️ Link removed between #{} and #{}.".format(note_a, note_b),
        )

    if req.intent == "note_links":
        short_id = req.entities.get("short_id")
        if not short_id:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Usage: /note links #<id>")
        phone = req.whatsapp_id
        with engine.connect() as conn:
            target = conn.execute(select(notes).where(
                notes.c.shortId == int(short_id), notes.c.triggerSource == phone
            )).mappings().first()
        if not target:
            return AlfredExecuteResponse(request_id=req.request_id, status="error", message="Note #{} not found.".format(short_id))
        with engine.connect() as conn:
            lnks = conn.execute(select(note_links).where(
                (note_links.c.note_id == target["id"]) | (note_links.c.linked_note_id == target["id"])
            )).mappings().all()
        linked_ids = [lnk["linked_note_id"] if lnk["note_id"] == target["id"] else lnk["note_id"] for lnk in lnks]
        explicit_shorts: list[tuple] = []
        if linked_ids:
            with engine.connect() as conn:
                exp_rows = conn.execute(select(notes).where(notes.c.id.in_(linked_ids))).mappings().all()
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
                past = conn.execute(select(notes).where(
                    notes.c.triggerSource == phone,
                    notes.c.id != target["id"],
                    notes.c.status == "active",
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
            lines.append("\U0001f517 Explicit links:")
            for sid, snip in explicit_shorts:
                lines.append("  #{}: {}".format(sid, snip))
        if entity_shorts:
            lines.append("\U0001f9e0 Entity-related:")
            for sid, snip in entity_shorts[:5]:
                lines.append("  #{}: {}".format(sid, snip))
        if not lines:
            return AlfredExecuteResponse(request_id=req.request_id, status="success", message="Note #{} has no related notes.".format(short_id))
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message="Note #{} connections:\n".format(short_id) + "\n".join(lines),
        )

    return AlfredExecuteResponse(
        request_id=req.request_id, status="error",
        error_code="NOT_FOUND", message="Unknown intent",
    )
