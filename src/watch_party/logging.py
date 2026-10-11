"""Structured event logging (Phase 8, S-2).

Logs room code, user id and event type - never tokens, payloads or chat
content. Safe for production log aggregation.
"""

import logging
import sys

logger = logging.getLogger("watch_party")

# Only these context keys may be logged (whitelist, defence in depth).
_SAFE_KEYS = frozenset({"action", "code", "reason", "detail", "role", "status"})

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Send logs to the terminal.

    Without this Python only surfaces WARNING+, so every logger.info() call
    (event logs, HTTP route logs, WS connect logs) would be silently dropped.
    """
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Shared logger for request/route logging."""
    return logging.getLogger(name) if name else logger


def log_event(
    event_type: str,
    *,
    user_id: str | None = None,
    room_code: str | None = None,
    **context: object,
) -> None:
    safe = {key: value for key, value in context.items() if key in _SAFE_KEYS}
    logger.info(
        "event=%s user=%s room=%s %s",
        event_type,
        user_id,
        room_code,
        " ".join(f"{key}={value}" for key, value in safe.items()),
    )
    # Mirror into the diagnostics buffer so /debug/events shows the same trail.
    from watch_party.debug.recorder import record

    record(
        "message",
        event=event_type,
        room=(room_code or "").upper(),
        user=user_id,
        **safe,
    )
