import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import insert

from database import engine, weavings
from services import qdrant_service, decision_arbiter

logger = logging.getLogger("brain.weaver")

# Financial events have no explicit intent vector yet in v0.9.
# Use a fixed proxy: moderate urgency, low social bond, higher goal alignment.
_EXPENSE_INTENT_PROXY = [0.4, 0.2, 0.6]

# Calibrated thresholds for text-embedding-3-small cross-lingual (zh/en) pairs.
# Pure English pairs typically score 0.72+; cross-lingual pairs score 0.45-0.60.
_LIFE_COSINE_THRESHOLD = 0.44
_INTENT_DOT_THRESHOLD = 0.3


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def check_for_weavings(
    family_id: str,
    user_id: str,
    thread_id: str,
    thread_embedding: list[float],
    intent_vector: dict,
    acl_tier: str = "shared",
) -> list[str]:
    """
    Search for OurCents expenses semantically similar to the new thread.
    For each match that passes dual thresholds, create a Weaving proposal.
    Returns list of created weaving IDs.
    """
    candidates = qdrant_service.find_similar_expenses(
        family_id, thread_embedding, score_threshold=_LIFE_COSINE_THRESHOLD
    )
    logger.info(
        "Weaving search for thread=%s family=%s → %d candidates (threshold=%.2f)",
        thread_id, family_id, len(candidates), _LIFE_COSINE_THRESHOLD,
    )
    if not candidates:
        return []

    iv_list = [
        float(intent_vector.get("urgency", 0.5)),
        float(intent_vector.get("social_bond", 0.5)),
        float(intent_vector.get("goal_alignment", 0.5)),
    ]

    created = []
    for result in candidates:
        fact_cosine = result.score
        intent_dot = _dot(iv_list, _EXPENSE_INTENT_PROXY)

        logger.info(
            "Candidate expense=%s cosine=%.3f intent_dot=%.3f",
            result.payload.get("expense_id", "?"), fact_cosine, intent_dot,
        )
        if intent_dot <= _INTENT_DOT_THRESHOLD or fact_cosine <= _LIFE_COSINE_THRESHOLD:
            continue

        arbiter_result = decision_arbiter.arbitrate(family_id, user_id, level=1)
        if arbiter_result != "APPROVED":
            logger.info(
                "Weaving skipped (%s): thread=%s expense=%s",
                arbiter_result, thread_id,
                result.payload.get("expense_id", "?"),
            )
            continue

        expense_id = result.payload.get("expense_id", "")
        expense_label = result.payload.get("merchant_name") or result.payload.get("expense_id", "expense")
        thread_label = result.payload.get("content", "thread")[:40] if False else thread_id[:8]

        weaving_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        try:
            with engine.connect() as conn:
                conn.execute(insert(weavings).values(
                    id=weaving_id,
                    family_id=family_id,
                    title=f"Thread #{thread_label} ↔ {expense_label}",
                    source_thread_id=thread_id,
                    source_expense_id=expense_id,
                    intent_vector_json=json.dumps(intent_vector),
                    fact_cosine=fact_cosine,
                    status="proposed",
                    acl_tier=acl_tier,
                    created_at=now,
                ))
                conn.commit()
            logger.info(
                "Weaving proposed: %s (thread=%s ↔ expense=%s, cosine=%.3f, intent_dot=%.3f)",
                weaving_id, thread_id, expense_id, fact_cosine, intent_dot,
            )
            created.append(weaving_id)
        except Exception as exc:
            logger.error("Failed to insert weaving: %s", exc)

    return created
