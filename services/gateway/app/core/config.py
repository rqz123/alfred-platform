from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Alfred"
    environment: str = "development"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 720
    admin_username: str = "admin"
    admin_password: str = "admin123"
    database_url: str = "sqlite:///./alfred.db"
    frontend_origin: str = "http://localhost:5173"
    frontend_origin_alt: str = "http://127.0.0.1:5173"
    whatsapp_mode: str = "bridge"
    bridge_api_url: str = "http://127.0.0.1:3001"
    bridge_api_key: str = "change-me-bridge-key"
    whatsapp_api_version: str = "v21.0"
    whatsapp_verify_token: str = "verify-token"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = ""
    stt_provider: str = "mock"
    stt_openai_api_key: str = ""
    stt_openai_model: str = "gpt-4o-mini-transcribe"
    tts_provider: str = "disabled"
    tts_openai_api_key: str = ""
    tts_openai_model: str = "gpt-4o-mini-tts"
    tts_openai_voice: str = "alloy"
    tts_audio_format: str = "mp3"

    model_config = SettingsConfigDict(
        # Try root monorepo .env first, then local .env for overrides
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()