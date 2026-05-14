import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import insert

from database import engine, brain_events
from services import active_pool, qdrant_service, weaving_detector
from services.embedding_service import get_embedding

logger = logging.getLogger("brain.processor")


def process_create_event(event: dict) -> None:
    """
    Handle a CREATE event from Gateway. Embeds the payload into Qdrant,
    updates Active Pool, and triggers Weaving detection for threads.
    """
    event_type = event.get("event_type", "")
    entities = event.get("entities") or {}
    user_id = event.get("user_id", "")
    family_id = event.get("family_id", "")

    if not family_id:
        logger.debug("Skipping event with no family_id: %s", event_type)
        _persist_event(event, processed=True)
        return

    try:
        if event_type == "add_thread":
            _process_thread(event, entities, user_id, family_id)
        elif event_type in ("add_expense", "add_income", "process_receipt_image"):
            _process_expense(event, entities, user_id, family_id)
        else:
            logger.debug("Unhandled event type for Brain: %s", event_type)

        _persist_event(event, processed=True)
    except Exception as exc:
        logger.error("process_create_event failed (%s): %s", event_type, exc)
        _persist_event(event, processed=False)


def _process_thread(event: dict, entities: dict, user_id: str, family_id: str) -> None:
    content = entities.get("content") or entities.get("title") or ""
    if not content:
        logger.debug("Thread event has no content, skipping embed")
        return

    thread_id = entities.get("thread_id") or str(uuid.uuid4())
    intent_vector = entities.get("intent_vector") or {
        "urgency": 0.5, "social_bond": 0.5, "goal_alignment": 0.5
    }

    embedding = get_embedding(content)

    category = entities.get("category") or "life"
    trigger_type = (entities.get("trigger") or {}).get("type") or "none"

    acl_tier = entities.get("acl_tier") or "shared"

    qdrant_service.upsert_thread(
        family_id=family_id,
        thread_id=thread_id,
        embedding=embedding,
        payload={
            "user_id": user_id,
            "content": content[:200],
            "category": category,
            "trigger_type": trigger_type,
            "acl_tier": acl_tier,
            "intent_vector": [
                float(intent_vector.get("urgency", 0.5)),
                float(intent_vector.get("social_bond", 0.5)),
                float(intent_vector.get("goal_alignment", 0.5)),
            ],
            "lock_status": "ready",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    active_pool.add(
        node_id=f"thread:{thread_id}",
        family_id=family_id,
        node_type="thread",
        score=float(intent_vector.get("urgency", 0.5)),
    )

    weaving_detector.check_for_weavings(
        family_id=family_id,
        user_id=user_id,
        thread_id=thread_id,
        thread_embedding=embedding,
        intent_vector=intent_vector,
        acl_tier=acl_tier,
    )


def _process_expense(event: dict, entities: dict, user_id: str, family_id: str) -> None:
    expense_id = entities.get("expense_id") or str(uuid.uuid4())
    merchant = entities.get("merchant_name") or entities.get("merchant") or ""
    category = entities.get("category") or ""
    amount = str(entities.get("amount") or "")

    text = " ".join(filter(None, [merchant, category, amount])).strip()
    if not text:
        logger.debug("Expense event has no text content, skipping embed")
        return

    embedding = get_embedding(text)

    qdrant_service.upsert_expense(
        family_id=family_id,
        expense_id=expense_id,
        embedding=embedding,
        payload={
            "user_id": user_id,
            "merchant_name": merchant,
            "category": category,
            "amount": amount,
            "lock_status": "ready",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    active_pool.add(
        node_id=f"expense:{expense_id}",
        family_id=family_id,
        node_type="expense",
        score=0.5,
    )


def _persist_event(event: dict, processed: bool) -> None:
    try:
        with engine.connect() as conn:
            conn.execute(insert(brain_events).values(
                id=str(uuid.uuid4()),
                event_action=event.get("event_action", "CREATE"),
                event_type=event.get("event_type"),
                entity_id=event.get("entity_id"),
                user_id=event.get("user_id"),
                family_id=event.get("family_id"),
                entities_json=json.dumps(event.get("entities") or {}),
                processed=processed,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
            conn.commit()
    except Exception as exc:
        logger.error("Failed to persist brain event: %s", exc)
