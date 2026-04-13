import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from database import create_tables, engine, reminders

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")
NUDGE_API_KEY = os.environ.get("ALFRED_API_KEY", "")

logger = logging.getLogger("nudge.firing")

FIRE_INTERVAL = int(os.environ.get("NUDGE_FIRE_INTERVAL_SECONDS", "60"))


async def _fire_due_reminders() -> None:
    """Check for due reminders and push notifications via Gateway."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with engine.connect() as conn:
            due = conn.execute(
                select(reminders).where(
                    reminders.c.status == "active",
                    reminders.c.nextFireAt <= now,
                )
            ).mappings().all()

        if not due:
            return

        for r in due:
            reminder_id = r["id"]
            title = r["title"]
            body_text = r.get("body") or title
            cron = r.get("cronExpression")
            tz_name = r.get("timezone", "Asia/Shanghai")
            trigger_source = r.get("triggerSource") or ""

            # Only push if the reminder was created via WhatsApp (has a phone in triggerSource)
            # or if triggerSource contains a phone number
            phone = None
            if trigger_source and any(c.isdigit() for c in trigger_source):
                phone = ''.join(c for c in trigger_source if c.isdigit() or c == '+')

            if phone:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        await client.post(
                            f"{GATEWAY_URL}/api/internal/push",
                            json={
                                "user_phone": phone,
                                "message": f"⏰ 提醒：{body_text}",
                                "source_service": "nudge",
                                "quick_replies": ["查看我的提醒"],
                            },
                            headers={"X-Alfred-API-Key": NUDGE_API_KEY},
                        )
                    logger.info("Fired reminder %s to %s", reminder_id, phone)
                except Exception as exc:
                    logger.warning("Push failed for reminder %s: %s", reminder_id, exc)

            # Update reminder state
            from services.parser import compute_next_fire
            if cron:
                next_fire = compute_next_fire(cron, tz_name)
                new_status = "active"
            else:
                next_fire = None
                new_status = "fired"

            with engine.connect() as conn:
                conn.execute(
                    update(reminders)
                    .where(reminders.c.id == reminder_id)
                    .values(
                        status=new_status,
                        lastFiredAt=now,
                        nextFireAt=next_fire,
                        updatedAt=now,
                    )
                )
                conn.commit()

    except Exception as exc:
        logger.error("Reminder firing loop error: %s", exc)


async def _reminder_loop() -> None:
    """Background loop that fires due reminders every FIRE_INTERVAL seconds."""
    while True:
        await asyncio.sleep(FIRE_INTERVAL)
        await _fire_due_reminders()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_tables()
    task = asyncio.create_task(_reminder_loop())
    logger.info("Reminder firing loop started (interval=%ds)", FIRE_INTERVAL)
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Nudge API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(nudge_router, prefix="/api/nudge")
