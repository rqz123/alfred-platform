import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select, update

from config import get_settings
from database import engine, weavings, correction_memory, kill_switches, persona_profiles
from services import qdrant_service, active_pool
from services.event_processor import process_create_event

logger = logging.getLogger("brain.router")

router = APIRouter()


def _require_api_key(x_api_key: str = Header(alias="X-API-Key", default="")):
    settings = get_settings()
    if not settings.brain_api_key or x_api_key != settings.brain_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


# ── Health ──────────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok", "service": "brain", "pool_size": active_pool.size()}


# ── Capabilities (for service registry) ──────────────────────────────────────

@router.get("/alfred/capabilities")
def capabilities(x_api_key: str = Header(alias="X-API-Key", default="")):
    _require_api_key(x_api_key)
    return {
        "service": "brain",
        "intents": [],  # Brain receives events, not skill dispatches in v0.9
    }


# ── Event ingestion ──────────────────────────────────────────────────────────

@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def ingest_event(
    event: dict,
    x_api_key: str = Header(alias="X-API-Key", default=""),
):
    _require_api_key(x_api_key)

    action = event.get("event_action", "")
    if action == "CREATE":
        import threading
        threading.Thread(
            target=process_create_event,
            args=(event,),
            daemon=True,
        ).start()
    elif action == "INVALIDATE":
        logger.info("INVALIDATE event received for entity %s (deferred to v1.1)", event.get("entity_id"))
    elif action == "USER_CORRECTION":
        _handle_user_correction(event)
    else:
        logger.warning("Unknown event_action: %s", action)

    return {"accepted": True}


def _handle_user_correction(event: dict) -> None:
    """Store correction in correction_memory and mark weaving as corrected."""
    import uuid
    weaving_id = event.get("entity_id", "")
    family_id = event.get("family_id", "")
    user_id = event.get("user_id", "")
    reason = event.get("correction_reason")
    now = datetime.now(timezone.utc).isoformat()

    try:
        with engine.connect() as conn:
            # Get the weaving to find source nodes
            row = conn.execute(
                select(weavings).where(weavings.c.id == weaving_id)
            ).first()

            if row:
                conn.execute(
                    update(weavings)
                    .where(weavings.c.id == weaving_id)
                    .values(status="corrected")
                )
                conn.execute(correction_memory.insert().values(
                    id=str(uuid.uuid4()),
                    family_id=family_id,
                    source_node_id=row.source_thread_id or "",
                    target_node_id=row.source_expense_id or "",
                    correction_type="disconnect",
                    reason=reason,
                    penalty_coefficient=0.1,
                    created_at=now,
                ))
                conn.commit()
                logger.info("USER_CORRECTION applied to weaving %s by %s", weaving_id, user_id)
    except Exception as exc:
        logger.error("USER_CORRECTION failed: %s", exc)


# ── Graph data ───────────────────────────────────────────────────────────────

@router.get("/graph/{family_id}")
def get_graph(family_id: str):
    nodes = qdrant_service.get_graph_nodes(family_id)

    # Compute heat for each node from Active Pool
    pool_nodes = {n["id"]: n for n in active_pool.get_family_nodes(family_id)}

    graph_nodes = []
    for n in nodes:
        node_id = n.get("thread_id") or n.get("expense_id") or n["id"]
        pool_key_thread = f"thread:{node_id}"
        pool_key_expense = f"expense:{node_id}"
        pool_entry = pool_nodes.get(pool_key_thread) or pool_nodes.get(pool_key_expense)
        heat = pool_entry["score"] if pool_entry else 0.3

        graph_nodes.append({
            "id": node_id,
            "type": n.get("type", "thread"),
            "label": (n.get("content") or n.get("merchant_name") or node_id)[:50],
            "heat": heat,
            "urgency": (n.get("intent_vector") or [0.5])[0] if n.get("intent_vector") else 0.5,
            "social_bond": (n.get("intent_vector") or [0.5, 0.5])[1] if n.get("intent_vector") else 0.5,
            "goal_alignment": (n.get("intent_vector") or [0.5, 0.5, 0.5])[2] if n.get("intent_vector") else 0.5,
            "created_at": n.get("created_at", ""),
            "family_id": family_id,
        })

    # Fetch weaving edges
    edges = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(weavings).where(
                    weavings.c.family_id == family_id,
                    weavings.c.status.in_(["proposed", "confirmed", "corrected"]),
                )
            ).mappings().all()
            for row in rows:
                edges.append({
                    "id": row["id"],
                    "source": row["source_thread_id"] or "",
                    "target": row["source_expense_id"] or "",
                    "type": "cross_skill",
                    "weight": row["fact_cosine"] or 0.0,
                    "status": row["status"],
                    "weaving_id": row["id"],
                })
    except Exception as exc:
        logger.error("get_graph edges failed: %s", exc)

    return {
        "nodes": graph_nodes,
        "edges": edges,
        "family_id": family_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Weaving management ────────────────────────────────────────────────────────

@router.get("/weavings/by_id/{weaving_id}")
def get_weaving_by_id(
    weaving_id: str,
    x_api_key: str = Header(alias="X-API-Key", default=""),
):
    """Fetch a single weaving by its ID. Used by onboarding Entry Hook."""
    _require_api_key(x_api_key)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                select(weavings).where(weavings.c.id == weaving_id)
            ).mappings().first()
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weaving not found")
            weaving = dict(row)
            # Fail closed: only weavings with explicit shared/family_private ACL are eligible as Entry Hooks
            if weaving.get("acl_tier") not in ("shared", "family_private"):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Entry Hook not available for this weaving")
            return weaving
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_weaving_by_id failed: %s", exc)
        raise


@router.get("/weavings/{family_id}")
def list_weavings(family_id: str):
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(weavings).where(weavings.c.family_id == family_id)
                .order_by(weavings.c.created_at.desc())
            ).mappings().all()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("list_weavings failed: %s", exc)
        return []


@router.post("/weavings/{weaving_id}/confirm")
def confirm_weaving(weaving_id: str):
    now = datetime.now(timezone.utc).isoformat()
    try:
        with engine.connect() as conn:
            conn.execute(
                update(weavings)
                .where(weavings.c.id == weaving_id)
                .values(status="confirmed", confirmed_at=now)
            )
            conn.commit()
        return {"ok": True, "status": "confirmed"}
    except Exception as exc:
        logger.error("confirm_weaving failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/weavings/{weaving_id}/correct")
def correct_weaving(weaving_id: str, body: dict = {}):
    reason = body.get("reason")
    _handle_user_correction({
        "entity_id": weaving_id,
        "family_id": body.get("family_id", ""),
        "user_id": body.get("user_id", ""),
        "correction_reason": reason,
    })
    return {"ok": True, "status": "corrected"}


# ── Debug endpoints ────────────────────────────────────────────────────────────

@router.get("/active_pool/{family_id}")
def debug_active_pool(family_id: str):
    return active_pool.get_family_nodes(family_id)


@router.get("/emotional_budget/{user_id}")
def debug_budget(user_id: str, family_id: str = ""):
    from services.decision_arbiter import _DAILY_BUDGET
    from sqlalchemy import func
    from datetime import timedelta
    from database import nudge_log
    now = datetime.now(timezone.utc)
    budget_start = (now - timedelta(hours=24)).isoformat()
    try:
        with engine.connect() as conn:
            q = select(func.sum(nudge_log.c.cost)).where(
                nudge_log.c.sent_at >= budget_start,
                nudge_log.c.user_id == user_id,
            )
            spent = conn.execute(q).scalar() or 0.0
        return {"user_id": user_id, "spent_24h": spent, "remaining": _DAILY_BUDGET - spent}
    except Exception as exc:
        return {"error": str(exc)}


# ── Kill Switch ───────────────────────────────────────────────────────────────

@router.post("/personas", status_code=status.HTTP_204_NO_CONTENT)
def init_persona(body: dict, x_alfred_key: str = Header(alias="X-Alfred-API-Key", default="")):
    """Initialize a PersonaProfile for a new user at first WhatsApp binding."""
    settings = get_settings()
    if x_alfred_key != settings.alfred_internal_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid key")

    user_phone = body.get("user_phone", "")
    family_id = body.get("family_id", "")
    if not user_phone or not family_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user_phone and family_id required")

    persona_id = f"{family_id}:{user_phone}"
    now = datetime.now(timezone.utc).isoformat()

    # Kelly gets implicit_ack enabled; everyone else defaults to False (Patch E)
    display_name = body.get("display_name")
    implicit_ack = body.get("implicit_ack_enabled", False)

    try:
        with engine.connect() as conn:
            existing = conn.execute(
                select(persona_profiles).where(persona_profiles.c.id == persona_id)
            ).first()
            if not existing:
                conn.execute(persona_profiles.insert().values(
                    id=persona_id,
                    family_id=family_id,
                    user_phone=user_phone,
                    display_name=display_name,
                    implicit_ack_enabled=implicit_ack,
                    implicit_ack_weight_increment=0.05,
                    implicit_ack_weight_cap=0.4,
                    silence_veto_phrase="stop for now",
                    inactivity_pause_days=7,
                    created_at=now,
                    updated_at=now,
                ))
                conn.commit()
                logger.info("PersonaProfile created for %s/%s", family_id, user_phone)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/kill_switch/{family_id}")
def set_kill_switch(family_id: str, body: dict = {}):
    active_flag = bool(body.get("active", False))
    now = datetime.now(timezone.utc).isoformat()
    try:
        with engine.connect() as conn:
            existing = conn.execute(
                select(kill_switches).where(kill_switches.c.family_id == family_id)
            ).first()
            if existing:
                conn.execute(
                    update(kill_switches)
                    .where(kill_switches.c.family_id == family_id)
                    .values(active=active_flag, updated_at=now)
                )
            else:
                conn.execute(kill_switches.insert().values(
                    family_id=family_id, active=active_flag, updated_at=now
                ))
            conn.commit()
        return {"family_id": family_id, "kill_switch": active_flag}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
