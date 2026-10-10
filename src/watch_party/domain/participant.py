"""Participant: one member of a Room (architecture section 7).

Holds the live WebSocket when online; offline members carry `websocket=None`.
No FastAPI imports: the websocket is duck-typed.
"""

import asyncio
from typing import Any

from watch_party.domain.roles import Role


class Participant:
    def __init__(
        self,
        user_id: str,
        username: str,
        role: Role,
        joined_at: float = 0.0,
    ) -> None:
        self.user_id = user_id
        self.username = username
        self.role = role
        self.joined_at = joined_at
        # Stub replaced by the real connection in the endpoint (kept for dispatch/dup handling).
        self.connection: Any | None = None

    @property
    def online(self) -> bool:
        return self.connection is not None

    async def send(self, event: dict[str, Any]) -> None:
        """Send with a timeout so one slow client cannot block the room (R-1)."""
        if self.connection is None:
            return
        try:
            await asyncio.wait_for(self.connection.send(event), timeout=2.0)
        except (TimeoutError, ConnectionError, RuntimeError):
            # A dead socket is handled by the normal leave flow.
            pass

    def snapshot(self) -> dict[str, Any]:
        """Wire form (8.0): { userId, username, role, online }."""
        return {
            "userId": self.user_id,
            "username": self.username,
            "role": self.role.value,
            "online": self.online,
        }
