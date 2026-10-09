from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://watch:watch@127.0.0.1:5432/watchparty"
    # NoDecode: keep the raw string from .env so the validator can accept CSV, not just JSON.
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    log_level: str = "INFO"

    # WebSocket foundation (Phase 1). Values from architecture sections 8.5, 10.1, 10.6, S-6, S-7.
    join_timeout_seconds: float = 5.0
    ws_ping_interval_seconds: float = 20.0
    ws_ping_timeout_seconds: float = 40.0
    ws_max_size_bytes: int = 65536
    ws_rate_limit_other_per_second: float = 20.0
    # Per-connection abuse limits: sustained violations close the socket (S-5, S-7).
    ws_max_invalid_per_window: int = 10
    ws_abuse_window_seconds: float = 60.0
    # Origin policy (S-3). False = reject a missing Origin header; true is local-only.
    allow_missing_origin: bool = False

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
