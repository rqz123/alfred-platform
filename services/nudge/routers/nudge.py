import sys
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# Add monorepo root to path for local dev so `shared` package is importable
# In Docker, shared is installed as a package so this is a no-op
_monorepo_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _monorepo_root not in sys.path:
    sys.path.insert(0, _monorepo_root)

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
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


# ─────────────────────────────────────────────────────
# ASI (Alfred Service Interface) endpoints
# ─────────────────────────────────────────────────────

_ALFRED_API_KEY = os.environ.get("ALFRED_API_KEY", "")


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
        "display_name": "Nudge 提醒助手",
        "capabilities": [
            {
                "intent": "add_reminder",
                "description": "添加提醒",
                "required_entities": [{"name": "title", "type": "string", "prompt_cn": "提醒内容是什么？"}],
                "optional_entities": [{"name": "date", "type": "date", "prompt_cn": "什么时候提醒？"}],
            },
            {"intent": "list_reminders", "description": "查看当前有效提醒"},
            {"intent": "get_schedule", "description": "查看今日日程"},
        ],
    }


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
                message="您目前没有待处理的提醒。",
                quick_replies=["添加提醒"],
            )
        lines = []
        for r in rows:
            fire = r.get("nextFireAt") or r.get("fireAt") or "待定"
            lines.append(f"• {r['title']} — {fire}")
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message="您的待办提醒：\n" + "\n".join(lines),
            quick_replies=["添加提醒"],
        )

    if req.intent in ("add_reminder", "get_schedule"):
        title = req.entities.get("title", "")
        if not title:
            return AlfredExecuteResponse(
                request_id=req.request_id, status="error",
                error_code="INSUFFICIENT_DATA",
                message="请告诉我提醒内容，例如：提醒我明天开会",
            )
        # Parse and create reminder using the existing parse service
        try:
            result = await parse_reminder(title, "Asia/Shanghai")
        except Exception:
            result = {"reminder": {"title": title, "type": "once", "fireAt": None,
                                   "cronExpression": None, "timezone": "Asia/Shanghai",
                                   "triggerSource": "whatsapp", "triggerCondition": None,
                                   "body": title},
                      "confidence": 0.5, "rawInterpretation": title}

        now = datetime.now(timezone.utc).isoformat()
        reminder_id = str(uuid.uuid4())
        parsed = result["reminder"]
        fire_at = parsed.get("fireAt")
        cron = parsed.get("cronExpression")
        next_fire = compute_next_fire(cron, parsed.get("timezone", "Asia/Shanghai")) if cron else fire_at

        row = {
            "id": reminder_id,
            "title": parsed.get("title", title),
            "body": parsed.get("body", title),
            "type": parsed.get("type", "once"),
            "fireAt": fire_at,
            "cronExpression": cron,
            "timezone": parsed.get("timezone", "Asia/Shanghai"),
            "triggerSource": req.whatsapp_id,
            "triggerCondition": parsed.get("triggerCondition"),
            "status": "active",
            "lastFiredAt": None,
            "nextFireAt": next_fire,
            "createdAt": now,
            "updatedAt": now,
        }
        with engine.connect() as conn:
            conn.execute(insert(reminders).values(**row))
            conn.commit()

        fire_display = next_fire or "待确认"
        return AlfredExecuteResponse(
            request_id=req.request_id, status="success",
            message=f"✅ 提醒已设置：{row['title']}\n时间：{fire_display}",
            quick_replies=["查看我的提醒"],
        )

    return AlfredExecuteResponse(
        request_id=req.request_id, status="error",
        error_code="NOT_FOUND", message="未知操作",
    )
