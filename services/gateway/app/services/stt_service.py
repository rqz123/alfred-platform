from fastapi import HTTPException, status
import httpx

from app.core.config import get_settings


def transcribe_audio_bytes(audio_bytes: bytes, filename: str, content_type: str) -> str:
    settings = get_settings()
    provider = settings.stt_provider.lower()

    if provider == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STT is disabled",
        )

    if provider == "mock":
        return f"Mock transcript generated for {filename}."

    if provider == "openai":
        api_key = settings.stt_openai_api_key or settings.openai_api_key
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenAI STT is not configured",
            )

        files = {
            "file": (filename, audio_bytes, content_type),
        }
        data = {
            "model": settings.stt_openai_model,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        try:
            response = httpx.post(
                "https://api.openai.com/v1/audio/transcriptions",
                data=data,
                files=files,
                headers=headers,
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"STT request failed: {exc}",
            ) from exc

        if response.is_error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=response.text or "STT request failed",
            )

        transcript = response.json().get("text")
        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="STT response did not include transcript text",
            )
        return transcript

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unsupported STT provider: {settings.stt_provider}",
    )