"""
Base configuration class for all Alfred platform services.

Each service subclasses BaseAppSettings and adds its own fields.
The root .env file is tried first; a local .env override is also supported.

  class GatewaySettings(BaseAppSettings):
      database_url: str = "sqlite:///./alfred.db"
      ...
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAppSettings(BaseSettings):
    # Shared across all services — set once in root .env
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 720
    openai_api_key: str = ""

    model_config = SettingsConfigDict(
        # Try root .env (for local dev run from service dir) then local .env
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
