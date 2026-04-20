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
NUDGE_API_KEY = os.environ.get("NUDGE_API_KEY", "") or os.environ.get("ALFRED_API_KEY", "")

logger = logging.getLogger("nudge.firing")


# ── Ack-retry config ────────────────────────────────────────────────────────
# After a reminder fires the user must reply OK.  If they don't, we re-fire
# every REFIRE_INTERVAL_SECONDS up to MAX_ACK_RETRIES extra times, then expire.
REFIRE_INTERVAL_SECONDS = int(os.environ.get("NUDGE_REFIRE_INTERVAL_SECONDS", "300"))
MAX_ACK_RETRIES = int(os.environ.get("NUDGE_MAX_ACK_RETRIES", "3"))

# ── Push-failure config (network errors, not user non-response) ──────────────
PUSH_MAX_RETRIES = 3
PUSH_RETRY_INTERVAL_SECONDS = 60   # 1 minute between push-failure retries


async def _push(phone: str, message: str, quick_replies: list[str]) -> bool:
    """Send a WhatsApp push via Gateway. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{GATEWAY_URL}/api/internal/push",
                json={"user_phone": phone, "message": message,
                      "source_service": "nudge", "quick_replies": quick_replies},
                headers={"X-Alfred-API-Key": NUDGE_API_KEY},
            )
        return True
    except Exception as exc:
        logger.warning("Push to %s failed: %s", phone, exc)
        return False


def _extract_phone(trigger_source: str) -> str | None:
    if trigger_source and any(c.isdigit() for c in trigger_source):
        return ''.join(c for c in trigger_source if c.isdigit() or c == '+')
    return None


async def _fire_due_reminders() -> None:
    """Fire due reminders and re-fire unacknowledged ones."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    try:
        with engine.connect() as conn:
            pending = conn.execute(
                select(reminders).where(
                    reminders.c.status.in_(["active", "awaiting"])
                )
            ).mappings().all()

        due = []
        for r in pending:
            nf = r.get("nextFireAt")
            if not nf:
                continue
            try:
                nf_dt = datetime.fromisoformat(nf)
                if nf_dt.tzinfo is None:
                    nf_dt = nf_dt.replace(tzinfo=timezone.utc)
                if nf_dt <= now_dt:
                    due.append(r)
            except Exception:
                pass

        if not due:
            return

        from services.parser import compute_next_fire
        for r in due:
            reminder_id = r["id"]
            status = r["status"]
            body_text = r.get("body") or r["title"]
            cron = r.get("cronExpression")
            tz_name = r.get("timezone", "UTC")
            phone = _extract_phone(r.get("triggerSource") or "")
            short_name = r.get("shortName") or ""
            label = f"\U0001f43e {short_name} \u2014 " if short_name else ""
            total_fires = MAX_ACK_RETRIES + 2   # initial + re-fires

            if status == "awaiting":
                # ── Re-fire: user hasn't acknowledged ────────────────────────
                ack_retries = int(r.get("ackRetries") or 0) + 1
                if ack_retries > MAX_ACK_RETRIES:
                    # Gave up — mark expired
                    logger.warning("Reminder %s expired after %d re-fires", reminder_id, ack_retries)
                    updates = dict(status="expired", nextFireAt=None, updatedAt=now)
                else:
                    suffix = f" (reminder {ack_retries + 1}/{total_fires})"
                    if ack_retries == MAX_ACK_RETRIES:
                        suffix += " \u2014 last reminder"
                    msg = f"{label}{body_text}{suffix}\nReply \u201cOK\u201d to confirm."
                    push_ok = await _push(phone, msg, ["\u2713 OK"]) if phone else True
                    if push_ok:
                        refire_dt = now_dt + timedelta(seconds=REFIRE_INTERVAL_SECONDS)
                        updates = dict(ackRetries=str(ack_retries), lastFiredAt=now,
                                       nextFireAt=refire_dt.isoformat(), updatedAt=now)
                        logger.info("Re-fired reminder %s (%d/%d) to %s",
                                    reminder_id, ack_retries, MAX_ACK_RETRIES, phone)
                    else:
                        # Push network failure — retry soon without incrementing ackRetries
                        push_retries = int(r.get("pushRetries") or 0) + 1
                        retry_dt = now_dt + timedelta(seconds=PUSH_RETRY_INTERVAL_SECONDS)
                        updates = dict(pushRetries=str(push_retries),
                                       nextFireAt=retry_dt.isoformat(), updatedAt=now)

            else:
                # ── Initial fire (status == "active") ────────────────────────
                push_retries = int(r.get("pushRetries") or 0)
                msg = f"{label}{body_text}\nReply \u201cOK\u201d to confirm."
                push_ok = await _push(phone, msg, ["\u2713 OK"]) if phone else True

                if push_ok:
                    refire_dt = now_dt + timedelta(seconds=REFIRE_INTERVAL_SECONDS)
                    updates = dict(status="awaiting", firstFiredAt=now, ackRetries="0",
                                   lastFiredAt=now, nextFireAt=refire_dt.isoformat(),
                                   pushRetries="0", updatedAt=now)
                    logger.info("Fired reminder %s to %s — awaiting ack", reminder_id, phone)
                else:
                    push_retries += 1
                    if push_retries <= PUSH_MAX_RETRIES:
                        retry_dt = now_dt + timedelta(seconds=PUSH_RETRY_INTERVAL_SECONDS)
                        updates = dict(pushRetries=str(push_retries),
                                       nextFireAt=retry_dt.isoformat(), updatedAt=now)
                    else:
                        logger.warning("Reminder %s push failed %d times — expiring",
                                       reminder_id, push_retries)
                        updates = dict(status="expired", lastFiredAt=now, nextFireAt=None,
                                       pushRetries=str(push_retries), updatedAt=now)

            with engine.connect() as conn:
                conn.execute(
                    update(reminders).where(reminders.c.id == reminder_id).values(**updates)
                )
                conn.commit()

    except Exception as exc:
        logger.error("Reminder firing loop error: %s", exc)


async def _reminder_loop() -> None:
    """Background loop that fires due reminders, aligned to minute boundaries."""
    # Fire once immediately on startup to catch anything missed while down
    await _fire_due_reminders()
    while True:
        # Sleep until the next whole minute so reminders fire at :00, not mid-minute
        now = datetime.now(timezone.utc)
        seconds_to_next_minute = 60 - now.second - now.microsecond / 1_000_000
        await asyncio.sleep(seconds_to_next_minute)
        await _fire_due_reminders()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_tables()
    task = asyncio.create_task(_reminder_loop())
    logger.info("Reminder firing loop started (minute-aligned)")
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
