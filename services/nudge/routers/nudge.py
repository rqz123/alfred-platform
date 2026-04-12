import sys
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

# Add monorepo root to path for local dev so `shared` package is importable
# In Docker, shared is installed as a package so this is a no-op
_monorepo_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _monorepo_root not in sys.path:
    sys.path.insert(0, _monorepo_root)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, insert

from shared.auth import make_verify_token, TokenPayload
from database import engine, reminders
from models import ParseRequest, ParseResponse, ParsedReminder, ReminderCreate, ReminderOut
from services.parser import parse_reminder, compute_next_fire

router = APIRouter()
verify_token = make_verify_token("/api/auth/login")


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
        next_fire = data.fireAt

    row = {
        "id": reminder_id,
        "title": data.title,
        "body": data.body,
        "type": data.type,
        "fireAt": data.fireAt,
        "cronExpression": data.cronExpression,
        "timezone": data.timezone,
        "triggerSource": data.triggerSource,
        "triggerCondition": data.triggerCondition,
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
