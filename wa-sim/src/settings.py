import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

GATEWAY_URL: str = os.environ.get("GATEWAY_URL", "http://localhost:8000")
BRIDGE_API_KEY: str = os.environ.get("BRIDGE_API_KEY", "change-me-bridge-key")
BRIDGE_PORT: int = int(os.environ.get("BRIDGE_PORT", "9001"))
SESSION_ID: str = os.environ.get("SESSION_ID", "sim-session-001")
DB_PATH: str = os.environ.get("DB_PATH", "")
