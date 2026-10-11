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
    # Every join-path DB call is bounded so a hung query cannot hold the room lock (R-6).
    ws_db_timeout_seconds: float = 5.0
    # Origin policy (S-3). False = reject a missing Origin header; true is local-only.
    allow_missing_origin: bool = False

    # Rooms and REST rate limits (Phase 2: 8.1, S-8, S-9).
    max_room_size: int = 20
    max_live_rooms_per_user: int = 3
    rest_rate_limit_per_minute: float = 30.0
    room_creation_rate_limit_per_minute: float = 5.0

    # Empty rooms close themselves after this long with nobody online (10.5).
    empty_room_ttl_seconds: float = 600.0

    # Host disconnect grace before auto-reassignment (D-15, 10.3).
    host_grace_seconds: float = 30.0

    # Playback state snapshots are debounced to one DB write per window (D-22).
    playback_debounce_seconds: float = 1.0

    # Approval requests (Phase 6): lifetime and sweeper cadence (8.3).
    request_ttl_seconds: float = 60.0
    request_sweep_seconds: float = 5.0

    # Per-connection rate limits for chat and reactions (S-7).
    chat_rate_limit_per_second: float = 3.0
    reaction_rate_limit_per_second: float = 5.0

    # Tests run the same engine from several event loops (sync tests via anyio.run
    # plus the TestClient portal); NullPool avoids cross-loop connection reuse.
    db_null_pool: bool = False

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
