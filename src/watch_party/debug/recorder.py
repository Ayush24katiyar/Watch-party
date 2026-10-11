"""Bounded recent-event buffer for the /debug endpoints.

Keeps the last N client messages, socket lifecycle events and rejections in
memory so a browser problem can be reconstructed from the terminal. Never
persisted, never holds payloads that could carry secrets (8.2, S-2).
"""

import time
from collections import deque
from typing import Any

# Bounded so a long dev session cannot grow this without limit.
_MAX_EVENTS = 200

_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_seq = 0


def record(kind: str, **fields: Any) -> None:
    """Append one diagnostic event. Safe to call from anywhere."""
    global _seq
    _seq += 1
    _events.append(
        {
            "seq": _seq,
            "at": round(time.time(), 3),
            "kind": kind,
            **fields,
        }
    )


def recent(limit: int = 50, room: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    """Newest-last slice of the buffer, optionally filtered."""
    events = list(_events)
    if room:
        needle = room.upper()
        events = [e for e in events if str(e.get("room", "")).upper() == needle]
    if kind:
        events = [e for e in events if e["kind"] == kind]
    return events[-limit:]


def clear() -> None:
    _events.clear()