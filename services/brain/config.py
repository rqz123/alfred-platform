import os
from functools import lru_cache


class BrainSettings:
    brain_database_url: str
    qdrant_url: str
    brain_api_key: str
    gateway_url: str
    thread_url: str
    thread_api_key: str
    alfred_internal_key: str
    openai_api_key: str
    frontend_origin: str
    frontend_origin_alt: str
    qdrant_enabled: bool

    def __init__(self):
        self.brain_database_url = os.environ.get(
            "BRAIN_DATABASE_URL", "sqlite:////data/brain.db"
        )
        self.qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        self.brain_api_key = (
            os.environ.get("BRAIN_API_KEY", "")
            or os.environ.get("ALFRED_API_KEY", "")
        )
        self.gateway_url = os.environ.get("GATEWAY_URL", "http://localhost:8000")
        self.thread_url = os.environ.get("THREAD_URL", "http://localhost:8002/api/thread")
        self.thread_api_key = os.environ.get("THREAD_API_KEY", "")
        self.alfred_internal_key = os.environ.get("ALFRED_INTERNAL_KEY", "")
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        self.frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
        self.frontend_origin_alt = os.environ.get(
            "FRONTEND_ORIGIN_ALT", "http://127.0.0.1:5173"
        )
        self.qdrant_enabled = os.environ.get("QDRANT_ENABLED", "true").lower() == "true"


@lru_cache
def get_settings() -> BrainSettings:
    return BrainSettings()
