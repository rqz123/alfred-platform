import logging
import threading
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from database import engine, nudge_log, kill_switches

logger = logging.getLogger("brain.arbiter")

# Cost per Nudge level
_LEVEL_COST = {1: 0.5, 2: 1.0, 3: 2.0, 4: 3.0}
_DAILY_BUDGET = 10.0
_DENSITY_WINDOW_HOURS = 2
_DENSITY_LIMIT = 4

# Process-level lock: makes check + log_nudge atomic so concurrent threads
# cannot both pass the density/budget checks before either writes to nudge_log.
_lock = threading.Lock()


def arbitrate(family_id: str, user_id: str | None = None, level: int = 1) -> str:
    """
    Run 3-check arbiter under a process lock. Returns "APPROVED", "DEFER", or "SUPPRESS".
    On APPROVED, writes to nudge_log atomically inside the lock.
    """
    cost = _LEVEL_COST.get(level, 0.5)
    now = datetime.now(timezone.utc)

    with _lock:
        try:
            with engine.connect() as conn:
                # Check 1: time window density (family-level)
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

                # Check 2: 24h emotional budget
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

                # Check 3: kill switch
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
