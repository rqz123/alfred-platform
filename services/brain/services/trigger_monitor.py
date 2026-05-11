"""
Trigger Monitor — Brain worker #6.

Responsibilities:
  - on_startup_misfire_check(): Patch A — scan for past-due triggers missed during downtime
  - run_trigger_monitor(): every 60s — fire due triggers with Weaving context (Patch D: atomic CAS)
  - scan_awaiting_timeouts(): every 60s — expire awaiting threads past their ack_timeout_at
"""

import logging
from datetime import datetime, timezone, timedelta

import httpx
from croniter import croniter
from sqlalchemy import select

from config import get_settings
from database import engine, weavings
from services.decision_arbiter import arbitrate

logger = logging.getLogger("brain.trigger_monitor")

_NUDGE_LEVEL = 2           # L2: explicit trigger nudge
_MISFIRE_INQUIRY_MAX = timedelta(hours=2)
_MISFIRE_FIRE_MAX = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Thread service helpers
# ---------------------------------------------------------------------------

def _thread_headers() -> dict:
    return {"X-Alfred-API-Key": get_settings().thread_api_key}


def _get_triggers(endpoint: str, **params) -> list[dict]:
    settings = get_settings()
    try:
        r = httpx.get(
            f"{settings.thread_url}/triggers/{endpoint}",
            params=params or None,
            headers=_thread_headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Failed to fetch triggers/%s: %s", endpoint, exc)
        return []


def _cas_status(thread_id: str, expected: str, new_status: str, **extra) -> bool:
    """Atomic compare-and-swap on trigger ack_status. Returns True on success."""
    settings = get_settings()
    payload = {"expected_status": expected, "new_status": new_status, **extra}
    try:
        r = httpx.patch(
            f"{settings.thread_url}/threads/{thread_id}/trigger-status",
            json=payload,
            headers=_thread_headers(),
            timeout=5.0,
        )
        return r.status_code == 200
    except Exception as exc:
        logger.warning("CAS update failed for thread %s: %s", thread_id, exc)
        return False


def _push(user_phone: str, message: str) -> bool:
    """Send a nudge to the user via Gateway internal push."""
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


# ---------------------------------------------------------------------------
# Weaving context
# ---------------------------------------------------------------------------

def _get_confirmed_weavings(thread_id: str, family_id: str | None) -> list[dict]:
    if not family_id:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(weavings).where(
                    weavings.c.family_id == family_id,
                    weavings.c.source_thread_id == thread_id,
                    weavings.c.status == "confirmed",
                )
            ).mappings().all()
        return [dict(r) for r in rows[:3]]
    except Exception as exc:
        logger.warning("Failed to fetch weavings for thread %s: %s", thread_id, exc)
        return []


def _build_message(thread: dict, context_weavings: list[dict]) -> str:
    content = thread.get("content", "")
    if not context_weavings:
        return content
    titles = [w.get("title", "") for w in context_weavings if w.get("title")]
    if not titles:
        return content
    related = "; ".join(titles[:3])
    return f"{content}\n\n(Related: {related})"


# ---------------------------------------------------------------------------
# Patch A: startup misfire check
# ---------------------------------------------------------------------------

def on_startup_misfire_check() -> None:
    """Scan for triggers that were pending but missed during downtime."""
    logger.info("Running startup misfire check")
    now = datetime.now(timezone.utc)
    # Fetch with a large window to capture everything past-due
    candidates = _get_triggers("pending", lookahead_minutes=60 * 24 * 365)

    past_due = []
    for t in candidates:
        fire_at_str = (t.get("trigger") or {}).get("fire_at")
        if not fire_at_str:
            continue
        try:
            fire_at = datetime.fromisoformat(fire_at_str.replace("Z", "+00:00"))
            if fire_at.tzinfo is None:
                fire_at = fire_at.replace(tzinfo=timezone.utc)
            if fire_at < now:
                past_due.append((t, fire_at))
        except Exception:
            continue

    logger.info("Misfire check: %d past-due trigger(s)", len(past_due))

    for thread, fire_at in past_due:
        thread_id = thread["thread_id"]
        trigger = thread.get("trigger", {})
        user_phone = thread.get("trigger_source")
        delay = now - fire_at

        if delay <= _MISFIRE_FIRE_MAX:
            # Small delay: leave as pending — run_trigger_monitor will fire it next cycle
            logger.info("Misfire: thread %s delayed %s, will re-fire", thread_id, delay)
        elif delay <= _MISFIRE_INQUIRY_MAX:
            # Moderate delay: ask the user
            if user_phone:
                content = thread.get("content", "")[:60]
                _push(user_phone, f'Earlier reminder: "{content}". Still relevant?')
            _cas_status(thread_id, "pending", "expired")
        else:
            # Long delay: mark expired and reschedule recurring
            _handle_expiry(thread_id, trigger, now, skip_followup=True)


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------

def run_trigger_monitor() -> None:
    """Scan for threads due to fire and send contextual nudges (runs every 60s)."""
    candidates = _get_triggers("pending", lookahead_minutes=5)
    if not candidates:
        return

    now = datetime.now(timezone.utc)
    logger.debug("Trigger monitor: %d candidate(s)", len(candidates))

    for thread in candidates:
        thread_id = thread["thread_id"]
        trigger = thread.get("trigger", {})
        user_phone = thread.get("trigger_source")
        family_id = thread.get("family_id")

        if not user_phone:
            continue

        # Patch D: atomic CAS — claim the thread before anyone else
        if not _cas_status(thread_id, "pending", "firing"):
            logger.debug("Thread %s already claimed, skipping", thread_id)
            continue

        try:
            ctx = _get_confirmed_weavings(thread_id, family_id)
            message = _build_message(thread, ctx)

            verdict = arbitrate(
                family_id=family_id or user_phone,
                user_id=user_phone,
                level=_NUDGE_LEVEL,
            )

            if verdict == "APPROVED":
                success = _push(user_phone, message)
                if success:
                    timeout_at = (now + timedelta(hours=2)).isoformat()
                    _cas_status(thread_id, "firing", "awaiting", ack_timeout_at=timeout_at)
                    logger.info("Fired nudge: thread %s → %s", thread_id, user_phone)
                else:
                    _cas_status(thread_id, "firing", "pending")
            else:
                _cas_status(thread_id, "firing", "pending")
                logger.debug("Thread %s nudge %s by arbiter", thread_id, verdict)

        except Exception as exc:
            logger.error("Trigger monitor error for thread %s: %s", thread_id, exc)
            _cas_status(thread_id, "firing", "pending")


# ---------------------------------------------------------------------------
# Awaiting timeout scanner
# ---------------------------------------------------------------------------

def scan_awaiting_timeouts() -> None:
    """Expire awaiting threads whose ack_timeout_at has passed (runs every 60s)."""
    now = datetime.now(timezone.utc)
    awaiting = _get_triggers("awaiting")

    for thread in awaiting:
        thread_id = thread["thread_id"]
        trigger = thread.get("trigger", {})
        ack_timeout_str = trigger.get("ack_timeout_at")
        if not ack_timeout_str:
            continue
        try:
            ack_timeout = datetime.fromisoformat(ack_timeout_str.replace("Z", "+00:00"))
            if ack_timeout.tzinfo is None:
                ack_timeout = ack_timeout.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if now < ack_timeout:
            continue

        _handle_expiry(thread_id, trigger, now)


# ---------------------------------------------------------------------------
# Shared expiry logic
# ---------------------------------------------------------------------------

def _handle_expiry(thread_id: str, trigger: dict, now: datetime, skip_followup: bool = False) -> None:
    """Mark a thread expired. Recurring threads get rescheduled silently."""
    trigger_type = trigger.get("type", "once")
    cron_expr = trigger.get("cron")
    current_status = trigger.get("ack_status", "pending")

    if trigger_type == "recurring" and cron_expr:
        try:
            next_fire = croniter(cron_expr, now).get_next(datetime).replace(tzinfo=timezone.utc)
            _cas_status(
                thread_id, current_status, "pending",
                fire_at=next_fire.isoformat(),
                ack_timeout_at=None,
            )
            logger.info("Rescheduled recurring thread %s → %s", thread_id, next_fire)
            return
        except Exception as exc:
            logger.warning("Failed to reschedule thread %s: %s", thread_id, exc)

    _cas_status(thread_id, current_status, "expired")
    logger.info("Expired thread %s (type=%s)", thread_id, trigger_type)


# ---------------------------------------------------------------------------
# Patch B — Adaptive geofence heartbeat
# ---------------------------------------------------------------------------

_GEOFENCE_HEARTBEAT_DEFAULT_SECS = 300   # 5 minutes when far from fence
_GEOFENCE_HEARTBEAT_NEAR_SECS = 30       # 30 seconds when near fence (< 500m)
_GEOFENCE_NEAR_THRESHOLD_METERS = 500


def update_geofence_heartbeat() -> None:
    """
    Patch B: scan active geofence threads and send heartbeat interval config
    to Gateway so the mobile client knows how often to report location.
    """
    settings = get_settings()
    try:
        r = httpx.get(
            f"{settings.thread_url}/triggers/pending",
            params={"trigger_type": "geofence"},
            headers=_thread_headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        geofence_threads = r.json()
    except Exception as exc:
        logger.warning("Failed to fetch geofence threads: %s", exc)
        return

    if not geofence_threads:
        return

    # Default heartbeat unless we know the user is near a fence
    interval_secs = _GEOFENCE_HEARTBEAT_DEFAULT_SECS
    try:
        httpx.post(
            f"{settings.gateway_url}/api/internal/location_heartbeat",
            json={"interval_seconds": interval_secs, "active_geofences": len(geofence_threads)},
            headers={"X-Alfred-API-Key": settings.alfred_internal_key},
            timeout=5.0,
        )
        logger.debug("Sent geofence heartbeat config: %ds for %d fences", interval_secs, len(geofence_threads))
    except Exception as exc:
        logger.warning("Failed to send geofence heartbeat: %s", exc)
