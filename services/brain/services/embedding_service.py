import logging
from openai import OpenAI
from config import get_settings

logger = logging.getLogger("brain.embedding")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=get_settings().openai_api_key)
    return _client


def get_embedding(text: str) -> list[float]:
    """Return a 1536-dim embedding for text using text-embedding-3-small."""
    try:
        resp = _get_client().embeddings.create(
            model="text-embedding-3-small",
            input=text[:8000],  # guard against oversized inputs
        )
        return resp.data[0].embedding
    except Exception as exc:
        logger.error("Embedding failed: %s", exc)
        return [0.0] * 1536
