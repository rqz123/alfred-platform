"""
Proactive Nudge Generator — daily Brain worker.

Scans the Active Pool for threads that haven't been referenced by any nudge
in the past 7 days and generates an L1 "memory recall" message for each user.
At most 1 proactive nudge per user per day.
"""

import logging
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import select, func, distinct

from config import get_settings
from database import engine, nudge_log, persona_profiles
from services.decision_arbiter import arbitrate

logger = logging.getLogger("brain.proactive_nudge")

_RECALL_IDLE_DAYS = 7
_NUDGE_LEVEL = 1   # L1: lightweight memory recall


def _thread_headers() -> dict:
    return {"X-Alfred-API-Key": get_settings().thread_api_key}


def _get_idle_threads(user_phone: str) -> list[dict]:
    """Return active threads for user_phone that haven't been updated in the past 7 days."""
    settings = get_settings()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_RECALL_IDLE_DAYS)).isoformat()
    try:
        r = httpx.get(
            f"{settings.thread_url}/alfred/threads",
            params={"user_phone": user_phone},
            headers=_thread_headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        all_threads = r.json()
    except Exception as exc:
        logger.warning("Failed to fetch threads for %s: %s", user_phone, exc)
        return []

    return [
        t for t in all_threads
        if (t.get("updatedAt") or t.get("createdAt") or "") < cutoff
    ]


def _already_nudged_today(family_id: str, user_phone: str) -> bool:
    """Return True if a proactive nudge was already sent today for this user."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    try:
        with engine.connect() as conn:
            count = conn.execute(
                select(func.count()).where(
                    nudge_log.c.family_id == family_id,
                    nudge_log.c.user_id == user_phone,
                    nudge_log.c.level == _NUDGE_LEVEL,
                    nudge_log.c.sent_at >= today_start,
                )
            ).scalar()
        return (count or 0) > 0
    except Exception as exc:
        logger.warning("Failed to query nudge_log: %s", exc)
        return False


def _push(user_phone: str, message: str) -> bool:
    settings = get_settings()
    try:
        r = httpx.post(
            f"{settings.gateway_url}/api/internal/push",
            json={"user_phone": user_phone, "message": message, "source_service": "brain"},
            headers={"X-Alfred-API-Key": settings.alfred_internal_key},
            timeout=10.0,
        )
        return r.status_code == 204
    except Exception as exc:
        logger.warning("Push failed for %s: %s", user_phone, exc)
        return False


def _build_recall_message(thread: dict) -> str:
    title = thread.get("title") or ""
    content = thread.get("content", "")
    preview = content[:120] + ("…" if len(content) > 120 else "")
    if title:
        return f"Just a gentle reminder about: *{title}*\n{preview}"
    return f"Checking in on something you noted a while back:\n{preview}"


def run_proactive_nudge(family_id: str, user_phone: str) -> None:
    """Daily task: send at most one L1 recall nudge per user for idle threads."""
    if _already_nudged_today(family_id, user_phone):
        logger.debug("Proactive nudge already sent today for %s", user_phone)
        return

    idle_threads = _get_idle_threads(user_phone)
    if not idle_threads:
        return

    # Pick the single most idle thread (oldest updatedAt)
    idle_threads.sort(key=lambda t: t.get("updatedAt") or t.get("createdAt") or "")
    thread = idle_threads[0]

    verdict = arbitrate(family_id=family_id, user_id=user_phone, level=_NUDGE_LEVEL)
    if verdict != "APPROVED":
        logger.info("Proactive nudge deferred for %s (arbiter: %s)", user_phone, verdict)
        return

    message = _build_recall_message(thread)
    success = _push(user_phone, message)
    if success:
        logger.info(
            "Proactive recall nudge sent to %s for thread %s",
            user_phone,
            thread.get("id"),
        )
    else:
        logger.warning("Proactive nudge push failed for %s", user_phone)


def _discover_users() -> list[tuple[str, str]]:
    """Return all known (family_id, user_phone) pairs from persona_profiles."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(persona_profiles.c.family_id, persona_profiles.c.user_phone)
                .where(persona_profiles.c.family_id.isnot(None))
            ).all()
        return [(r[0], r[1]) for r in rows if r[0] and r[1]]
    except Exception as exc:
        logger.warning("Failed to discover users: %s", exc)
        return []


def run_proactive_nudge_all() -> None:
    """Daily scheduler entry point: run proactive nudge for all known users."""
    users = _discover_users()
    if not users:
        logger.debug("No known users for proactive nudge scan")
        return
    for family_id, user_phone in users:
        try:
            run_proactive_nudge(family_id, user_phone)
        except Exception as exc:
            logger.warning(
                "Proactive nudge error for %s/%s: %s", family_id, user_phone, exc
            )
