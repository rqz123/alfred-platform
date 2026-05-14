import logging
import threading
import uuid
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import select, func

from database import engine, nudge_log, kill_switches

logger = logging.getLogger("brain.arbiter")

# Cost per Nudge level
_LEVEL_COST = {1: 0.5, 2: 1.0, 3: 2.0, 4: 3.0}
_DAILY_BUDGET = 10.0
_DENSITY_WINDOW_HOURS = 2
_DENSITY_LIMIT = 4

# Observer Mode: if family has >= this many inbound messages in 5 min, defer L1/L2 nudges
OBSERVER_MODE_THRESHOLD = 10
_OBSERVER_WINDOW_MINUTES = 5

# Process-level lock: makes check + log_nudge atomic so concurrent threads
# cannot both pass the density/budget checks before either writes to nudge_log.
_lock = threading.Lock()


def _check_observer_mode(family_id: str) -> bool:
    """Return True if the family is in a busy-conversation window (Observer Mode active)."""
    try:
        from config import get_settings
        cfg = get_settings()
        resp = httpx.get(
            f"{cfg.gateway_url}/api/internal/traffic/{family_id}",
            params={"window_minutes": _OBSERVER_WINDOW_MINUTES},
            headers={"X-Alfred-API-Key": cfg.alfred_internal_key},
            timeout=3.0,
        )
        if resp.is_error:
            logger.debug("Observer Mode check failed (non-2xx): %s", resp.status_code)
            return False
        count = resp.json().get("message_count", 0)
        return count >= OBSERVER_MODE_THRESHOLD
    except Exception as exc:
        logger.debug("Observer Mode check skipped: %s", exc)
        return False  # fail open


def arbitrate(family_id: str, user_id: str | None = None, level: int = 1) -> str:
    """
    Run Decision Arbiter checks. Returns "APPROVED", "DEFER", or "SUPPRESS".
    On APPROVED, writes to nudge_log atomically inside the lock.

    Checks (in order):
      1. Observer Mode (L1/L2 only) — DEFER if family is in active conversation spike
      2-4. Density, budget, kill-switch (under process lock)
    """
    cost = _LEVEL_COST.get(level, 0.5)
    now = datetime.now(timezone.utc)

    # Check 1: Observer Mode — skip for urgent levels L3/L4
    if level in (1, 2) and _check_observer_mode(family_id):
        logger.debug("Arbiter DEFER: Observer Mode active for family %s", family_id)
        return "DEFER"

    with _lock:
        try:
            with engine.connect() as conn:
                # Check 2: time window density (family-level)
                window_start = (now - timedelta(hours=_DENSITY_WINDOW_HOURS)).isoformat()
                density = conn.execute(
                    select(func.count()).where(
                        nudge_log.c.family_id == family_id,
                        nudge_log.c.sent_at >= window_start,
                    )
                ).scalar() or 0
                if density >= _DENSITY_LIMIT:
                    logger.debug("Arbiter DEFER: density=%d for family %s", density, family_id)
                    return "DEFER"

                # Check 3: 24h emotional budget
                budget_start = (now - timedelta(hours=24)).isoformat()
                q = select(func.sum(nudge_log.c.cost)).where(
                    nudge_log.c.family_id == family_id,
                    nudge_log.c.sent_at >= budget_start,
                )
                if user_id:
                    q = q.where(nudge_log.c.user_id == user_id)
                spent = conn.execute(q).scalar() or 0.0
                if spent + cost > _DAILY_BUDGET:
                    logger.debug(
                        "Arbiter DEFER: budget spent=%.1f + cost=%.1f > %.1f for %s",
                        spent, cost, _DAILY_BUDGET, user_id or family_id,
                    )
                    return "DEFER"

                # Check 4: kill switch
                row = conn.execute(
                    select(kill_switches.c.active).where(
                        kill_switches.c.family_id == family_id
                    )
                ).first()
                if row and row[0]:
                    logger.debug("Arbiter SUPPRESS: kill switch active for family %s", family_id)
                    return "SUPPRESS"

                # All checks passed — record atomically before releasing the lock
                conn.execute(nudge_log.insert().values(
                    id=str(uuid.uuid4()),
                    family_id=family_id,
                    user_id=user_id,
                    level=level,
                    cost=cost,
                    sent_at=now.isoformat(),
                ))
                conn.commit()

        except Exception as exc:
            logger.error("Arbiter error: %s", exc)
            return "APPROVED"  # fail open so Weavings are not permanently lost

    return "APPROVED"
