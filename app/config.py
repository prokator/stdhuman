from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "StdHuman Agent"
    port: int = 18081
    timeout: int = 3600
    telegram_bot_token: str
    dev_telegram_username: str
    telegram_poll_interval: float = 5.0

    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    @field_validator("dev_telegram_username")
    @classmethod
    def validate_dev_username(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed.startswith("@"):
            raise ValueError("DEV_TELEGRAM_USERNAME must start with '@'")
        return trimmed


settings = Settings()
