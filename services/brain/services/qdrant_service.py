import logging
import uuid
from typing import Any

from config import get_settings

logger = logging.getLogger("brain.qdrant")

_client = None
_VECTOR_SIZE = 1536
_COLLECTIONS = ("threads_all", "ourcents_expenses")

# Per-category cosine similarity thresholds for cross-category Weaving search
CATEGORY_THRESHOLDS: dict[str, float] = {
    "pro":     0.80,
    "life":    0.72,
    "emo":     0.65,
    "routine": 0.75,
}


def _get_client():
    """
    Return a Qdrant client. Three modes based on QDRANT_URL:
      - ":memory:"           → in-process in-memory (ephemeral, great for dev/test)
      - "local:///some/path" → in-process persistent file storage (no server needed)
      - "http://host:port"   → remote Qdrant server (Docker / production)
    """
    global _client
    if _client is None:
        from qdrant_client import QdrantClient
        url = get_settings().qdrant_url
        if url == ":memory:":
            _client = QdrantClient(":memory:")
            logger.info("Qdrant: in-memory mode")
        elif url.startswith("local://"):
            path = url[len("local://"):]  # strip "local://"
            _client = QdrantClient(path=path)
            logger.info("Qdrant: local file mode at %s", path)
        else:
            _client = QdrantClient(url=url, timeout=10)
            logger.info("Qdrant: remote server at %s", url)
    return _client


def ensure_collections() -> None:
    """Create Qdrant collections if they don't exist yet. Migrate threads_life → threads_all."""
    if not get_settings().qdrant_enabled:
        return
    from qdrant_client.models import VectorParams, Distance, PayloadSchemaType
    try:
        client = _get_client()
        existing = {c.name for c in client.get_collections().collections}

        # Migrate: threads_life was the old name; re-create points under threads_all
        if "threads_life" in existing and "threads_all" not in existing:
            logger.info("Migrating threads_life → threads_all")
            client.create_collection(
                collection_name="threads_all",
                vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
            )
            client.create_payload_index("threads_all", "family_id", PayloadSchemaType.KEYWORD)
            client.create_payload_index("threads_all", "lock_status", PayloadSchemaType.KEYWORD)
            client.create_payload_index("threads_all", "category", PayloadSchemaType.KEYWORD)
            # Copy all points from the old collection
            offset = None
            while True:
                results, next_offset = client.scroll(
                    "threads_life", limit=100, offset=offset, with_payload=True, with_vectors=True
                )
                if results:
                    from qdrant_client.models import PointStruct
                    client.upsert(
                        "threads_all",
                        points=[
                            PointStruct(
                                id=r.id,
                                vector=r.vector,
                                payload={**(r.payload or {}), "node_type": "thread"},
                            )
                            for r in results
                        ],
                    )
                if next_offset is None:
                    break
                offset = next_offset
            client.delete_collection("threads_life")
            logger.info("Migration threads_life → threads_all complete")
            existing = {c.name for c in client.get_collections().collections}

        for name in _COLLECTIONS:
            if name not in existing:
                client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
                )
                client.create_payload_index(name, "family_id", PayloadSchemaType.KEYWORD)
                client.create_payload_index(name, "lock_status", PayloadSchemaType.KEYWORD)
                if name == "threads_all":
                    client.create_payload_index(name, "category", PayloadSchemaType.KEYWORD)
                logger.info("Created Qdrant collection: %s", name)
    except Exception as exc:
        logger.error("Qdrant ensure_collections failed: %s", exc)


def upsert_thread(
    family_id: str,
    thread_id: str,
    embedding: list[float],
    payload: dict[str, Any],
) -> None:
    if not get_settings().qdrant_enabled:
        return
    from qdrant_client.models import PointStruct
    try:
        client = _get_client()
        point_id = _stable_uuid(thread_id)
        full_payload = {
            **payload,
            "family_id": family_id,
            "thread_id": thread_id,
            "node_type": "thread",
            "lock_status": "ready",
        }
        client.upsert(
            "threads_all",
            points=[PointStruct(id=point_id, vector=embedding, payload=full_payload)],
        )
    except Exception as exc:
        logger.error("upsert_thread failed for %s: %s", thread_id, exc)


def upsert_expense(
    family_id: str,
    expense_id: str,
    embedding: list[float],
    payload: dict[str, Any],
) -> None:
    if not get_settings().qdrant_enabled:
        return
    from qdrant_client.models import PointStruct
    try:
        client = _get_client()
        point_id = _stable_uuid(expense_id)
        full_payload = {
            **payload,
            "family_id": family_id,
            "expense_id": expense_id,
            "lock_status": "ready",
        }
        client.upsert(
            "ourcents_expenses",
            points=[PointStruct(id=point_id, vector=embedding, payload=full_payload)],
        )
    except Exception as exc:
        logger.error("upsert_expense failed for %s: %s", expense_id, exc)


def find_similar_expenses(
    family_id: str,
    thread_embedding: list[float],
    top_k: int = 5,
    score_threshold: float = 0.68,
) -> list[Any]:
    """Return Qdrant results above score_threshold for the given family."""
    if not get_settings().qdrant_enabled:
        return []
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    try:
        client = _get_client()
        result = client.query_points(
            "ourcents_expenses",
            query=thread_embedding,
            query_filter=Filter(
                must=[
                    FieldCondition(key="family_id", match=MatchValue(value=family_id)),
                    FieldCondition(key="lock_status", match=MatchValue(value="ready")),
                ]
            ),
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return result.points
    except Exception as exc:
        logger.error("find_similar_expenses failed: %s", exc)
        return []


def get_graph_nodes(family_id: str) -> list[dict]:
    """Return all ready nodes for a family across all collections."""
    if not get_settings().qdrant_enabled:
        return []
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    nodes = []
    try:
        client = _get_client()
        for collection, default_type in (("threads_all", "thread"), ("ourcents_expenses", "expense")):
            results, _ = client.scroll(
                collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="family_id", match=MatchValue(value=family_id)),
                        FieldCondition(key="lock_status", match=MatchValue(value="ready")),
                    ]
                ),
                limit=100,
                with_payload=True,
            )
            for r in results:
                payload = r.payload or {}
                node_type = payload.get("node_type", default_type)
                nodes.append({"id": str(r.id), "type": node_type, **payload})
    except Exception as exc:
        logger.error("get_graph_nodes failed: %s", exc)
    return nodes


def _stable_uuid(source_id: str) -> str:
    """Derive a deterministic UUID from a string ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, source_id))
