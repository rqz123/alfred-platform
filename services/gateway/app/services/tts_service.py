from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings


@dataclass
class SynthesizedSpeech:
    filename: str
    content_type: str
    audio_bytes: bytes


def synthesize_speech(text: str) -> SynthesizedSpeech:
    settings = get_settings()
    provider = settings.tts_provider.lower()

    if provider == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS is disabled",
        )

    if provider == "openai":
        if not settings.tts_openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenAI TTS is not configured",
            )

        payload = {
            "model": settings.tts_openai_model,
            "voice": settings.tts_openai_voice,
            "input": text,
            "format": settings.tts_audio_format,
        }
        headers = {
            "Authorization": f"Bearer {settings.tts_openai_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                "https://api.openai.com/v1/audio/speech",
                json=payload,
                headers=headers,
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"TTS request failed: {exc}",
            ) from exc

        if response.is_error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=response.text or "TTS request failed",
            )

        audio_format = settings.tts_audio_format.lower()
        content_type = "audio/mpeg" if audio_format == "mp3" else "audio/ogg"
        return SynthesizedSpeech(
            filename=f"speech.{audio_format}",
            content_type=content_type,
            audio_bytes=response.content,
        )

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unsupported TTS provider: {settings.tts_provider}",
    )