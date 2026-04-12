import base64
import logging
import mimetypes
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger("alfred.media")

# Stored alongside the DB: backend/media/
MEDIA_DIR = Path(__file__).resolve().parent.parent.parent / "media"

_EXT_FIX = {".jpe": ".jpg", ".jpeg": ".jpg"}


def ensure_media_dir() -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def _ext_for(mimetype: str) -> str:
    base = mimetype.split(";")[0].strip()
    ext = mimetypes.guess_extension(base) or ".bin"
    return _EXT_FIX.get(ext, ext)


def save_base64_media(data_b64: str, mimetype: str) -> str:
    ensure_media_dir()
    ext = _ext_for(mimetype)
    filename = f"{uuid4()}{ext}"
    path = MEDIA_DIR / filename
    path.write_bytes(base64.b64decode(data_b64))
    logger.info("Saved media %s (%s, %d bytes)", filename, mimetype, path.stat().st_size)
    return f"/api/media/{filename}"


def save_uploaded_media(raw: bytes, mimetype: str) -> str:
    ensure_media_dir()
    ext = _ext_for(mimetype)
    filename = f"{uuid4()}{ext}"
    path = MEDIA_DIR / filename
    path.write_bytes(raw)
    logger.info("Saved uploaded media %s (%s, %d bytes)", filename, mimetype, path.stat().st_size)
    return f"/api/media/{filename}"


def get_media_path(filename: str) -> Path | None:
    safe = Path(filename).name  # strip any path traversal
    path = MEDIA_DIR / safe
    return path if path.exists() else None
