import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from database import create_tables, engine, reminders
from routers.nudge import router as nudge_router

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")
NUDGE_API_KEY = os.environ.get("ALFRED_API_KEY", "")

logger = logging.getLogger("nudge.firing")

FIRE_INTERVAL = int(os.environ.get("NUDGE_FIRE_INTERVAL_SECONDS", "60"))


PUSH_MAX_RETRIES = 3
PUSH_RETRY_INTERVAL_SECONDS = 300   # 5 minutes between retries
PUSH_EXPIRY_SECONDS = 1800          # give up after 30 minutes


async def _fire_due_reminders() -> None:
    """Check for due reminders and push notifications via Gateway."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
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

        from services.parser import compute_next_fire
        for r in due:
            reminder_id = r["id"]
            title = r["title"]
            body_text = r.get("body") or title
            cron = r.get("cronExpression")
            tz_name = r.get("timezone", "UTC")
            trigger_source = r.get("triggerSource") or ""
            push_retries = int(r.get("pushRetries") or 0)

            # Extract phone from triggerSource
            phone = None
            if trigger_source and any(c.isdigit() for c in trigger_source):
                phone = ''.join(c for c in trigger_source if c.isdigit() or c == '+')

            push_ok = True
            if phone:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        await client.post(
                            f"{GATEWAY_URL}/api/internal/push",
                            json={
                                "user_phone": phone,
                                "message": f"Reminder: {body_text}",
                                "source_service": "nudge",
                                "quick_replies": ["View my reminders"],
                            },
                            headers={"X-Alfred-API-Key": NUDGE_API_KEY},
                        )
                    logger.info("Fired reminder %s to %s", reminder_id, phone)
                    push_retries = 0
                except Exception as exc:
                    push_ok = False
                    push_retries += 1
                    logger.warning(
                        "Push failed for reminder %s (attempt %d): %s",
                        reminder_id, push_retries, exc,
                    )

            # Determine next state
            if cron and push_ok:
                # Recurring: schedule next occurrence
                next_fire = compute_next_fire(cron, tz_name)
                new_status = "active"
                updates = dict(status=new_status, lastFiredAt=now, nextFireAt=next_fire,
                               pushRetries="0", updatedAt=now)
            elif not push_ok and push_retries <= PUSH_MAX_RETRIES:
                # Push failed but retries remain — reschedule soon
                retry_dt = now_dt + timedelta(seconds=PUSH_RETRY_INTERVAL_SECONDS)

                # Check if we're still within the expiry window
                fire_at_str = r.get("nextFireAt") or r.get("fireAt") or now
                try:
                    original_dt = datetime.fromisoformat(fire_at_str)
                    if original_dt.tzinfo is None:
                        original_dt = original_dt.replace(tzinfo=timezone.utc)
                    expired = (now_dt - original_dt).total_seconds() > PUSH_EXPIRY_SECONDS
                except Exception:
                    expired = False

                if expired:
                    logger.warning("Reminder %s push expired after %d retries", reminder_id, push_retries)
                    updates = dict(status="done", lastFiredAt=now, nextFireAt=None,
                                   pushRetries=str(push_retries), updatedAt=now)
                else:
                    logger.info("Scheduling retry %d for reminder %s at %s",
                                push_retries, reminder_id, retry_dt.isoformat())
                    updates = dict(nextFireAt=retry_dt.isoformat(),
                                   pushRetries=str(push_retries), updatedAt=now)
            elif not push_ok:
                # Exhausted retries
                logger.warning("Reminder %s push exhausted after %d retries", reminder_id, push_retries)
                updates = dict(status="done", lastFiredAt=now, nextFireAt=None,
                               pushRetries=str(push_retries), updatedAt=now)
            else:
                # One-time, push succeeded (or no phone — fire locally)
                updates = dict(status="done", lastFiredAt=now, nextFireAt=None,
                               pushRetries="0", updatedAt=now)

            with engine.connect() as conn:
                conn.execute(
                    update(reminders).where(reminders.c.id == reminder_id).values(**updates)
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
    allow_origins=[FRONTEND_ORIGIN, "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(nudge_router, prefix="/api/nudge")
