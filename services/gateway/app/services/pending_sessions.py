"""
In-memory store for pending multi-turn conversation sessions.

When a downstream service returns INSUFFICIENT_DATA, the dispatch layer
saves the partial intent + entities here so the next message from the
same phone number can be treated as a follow-up rather than a new request.

Design decisions:
- Storage: module-level dict (phone → PendingSession). Lost on restart,
  which is acceptable — a restart is equivalent to a timeout.
- Timeout: 5 minutes. Stale entries are evicted lazily on next access.
- Max retries: 2 follow-up attempts per pending session to avoid loops.
- Cancel: detected by keyword match before intent detection.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

TIMEOUT_SECONDS = 300   # 5 minutes
MAX_RETRIES = 2         # max follow-up rounds before giving up

# Cancel / abandon keywords (Unicode escapes keep the source ASCII-clean)
# \u53d6\u6d88=cancel, \u7b97\u4e86=forget-it, \u4e0d\u8981\u4e86=never-mind,
# \u6ca1\u4e8b=nothing, \u4e0d\u7528\u4e86=no-need
_CANCEL_KW = [
    '\u53d6\u6d88',
    '\u7b97\u4e86',
    '\u4e0d\u8981\u4e86',
    '\u6ca1\u4e8b',
    '\u4e0d\u7528\u4e86',
    'cancel',
    'nevermind',
    'never mind',
    'stop',
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PendingSession:
    intent: str
    entities: dict
    service: dict               # full service dict from ServiceRegistry
    expires_at: datetime = field(
        default_factory=lambda: _now() + timedelta(seconds=TIMEOUT_SECONDS)
    )
    retries: int = 0

    def is_expired(self) -> bool:
        return _now() > self.expires_at


# phone_number → PendingSession
_store: dict[str, PendingSession] = {}


def get(phone: str) -> Optional[PendingSession]:
    """Return the pending session for phone, or None if absent/expired."""
    s = _store.get(phone)
    if s is None:
        return None
    if s.is_expired():
        del _store[phone]
        return None
    return s


def save(phone: str, intent: str, entities: dict, service: dict) -> PendingSession:
    """Create or overwrite the pending session for phone."""
    s = PendingSession(intent=intent, entities=dict(entities), service=service)
    _store[phone] = s
    return s


def clear(phone: str) -> None:
    """Remove the pending session for phone (if any)."""
    _store.pop(phone, None)


def is_cancel(text: str) -> bool:
    """Return True if the text looks like a user abandon/cancel signal."""
    t = text.lower().strip()
    return any(kw in t for kw in _CANCEL_KW)
