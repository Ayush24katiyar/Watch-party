"""Room: in-memory live state for one room (architecture sections 7, D-2).

The Room is the live source of truth; Postgres holds rooms, members, roles and
the last playback snapshot. No FastAPI, no database imports (doc rule 4).
"""

import asyncio
import time
import uuid
from typing import Any, Iterator

from watch_party.domain.participant import Participant


class Room:
    def __init__(
        self,
        code: str,
        host_user_id: str,
        locked: bool = False,
        db_id: uuid.UUID | None = None,
    ) -> None:
        self.code = code.upper()
        self.host_user_id = host_user_id
        self.locked = locked
        # Database primary key, set when the room is restored/persisted.
        self.db_id = db_id
        self.participants: dict[str, Participant] = {}
        # D-13: one lock per room around membership/role/host changes.
        self.lock = asyncio.Lock()
        # Playback state (D-7); fields are unused until Phase 5.
        self.video_state: dict[str, Any] = {
            "video_id": None,
            "play_state": "paused",
            "position": 0.0,
            "seq": 0,
            "updated_at": time.monotonic(),
        }

    # ---- membership ----

    def add(self, participant: Participant) -> None:
        self.participants[participant.user_id] = participant

    def remove(self, user_id: str) -> None:
        self.participants.pop(user_id, None)

    def is_full(self, max_size: int) -> bool:
        # Capacity counts members (offline members keep their seat, 10.1/10.3).
        return len(self.participants) >= max_size

    # ---- wire form ----

    def participant_snapshots(self) -> list[dict[str, Any]]:
        return [participant.snapshot() for participant in self.participants.values()]

    def state_snapshot(self) -> dict[str, Any]:
        state = self.video_state
        current_time = state["position"]
        if state["play_state"] == "playing":
            current_time += max(0.0, time.monotonic() - state["updated_at"])
        return {
            "videoId": state["video_id"],
            "playState": state["play_state"],
            "currentTime": round(current_time, 2),
            "seq": state["seq"],
        }

    # ---- broadcast ----

    async def broadcast(self, event: dict[str, Any], exclude_user_id: str | None = None) -> None:
        """Send to everyone concurrently; failures never block the sender (R-1)."""
        tasks = [
            participant.send(event)
            for user_id, participant in self.participants.items()
            if user_id != exclude_user_id and participant.online
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def __iter__(self) -> Iterator[Participant]:
        return iter(self.participants.values())

    def __len__(self) -> int:
        return len(self.participants)
