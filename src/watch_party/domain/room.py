"""Room: in-memory live state for one room (architecture sections 7, D-2).

The Room is the live source of truth; Postgres holds rooms, members, roles and
the last playback snapshot. No FastAPI, no database imports (doc rule 4).
"""

import asyncio
import time
import uuid
import secrets
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
        # Phase 6: pending approval requests (in memory only, 8.3).
        self.pending_requests: dict[str, dict[str, Any]] = {}
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

    def remove(self, user_id: str) -> Participant | None:
        """Full removal (kick): the member row stays in the DB (banned, D-16)."""
        return self.participants.pop(user_id, None)

    def is_full(self, max_size: int) -> bool:
        # Capacity counts members (offline members keep their seat, 10.1/10.3).
        return len(self.participants) >= max_size

    def has_online_participants(self) -> bool:
        return any(participant.online for participant in self.participants.values())

    # ---- approval requests (Phase 6, section 8.3) ----

    def create_request(
        self, requester: Participant, action: str, payload: dict[str, Any], ttl_seconds: float
    ) -> dict[str, Any] | None:
        """Limits: 1 pending per user, 20 per room (16). Returns the request or None."""
        if any(r["user_id"] == requester.user_id for r in self.pending_requests.values()):
            return None
        if len(self.pending_requests) >= 20:
            return None
        request = {
            "requestId": secrets.token_urlsafe(12),
            "user_id": requester.user_id,
            "username": requester.username,
            "action": action,
            "payload": payload,
            "expiresAt": time.time() + ttl_seconds,
        }
        self.pending_requests[request["requestId"]] = request
        return request

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        return self.pending_requests.get(request_id)

    def remove_request(self, request_id: str) -> None:
        self.pending_requests.pop(request_id, None)

    def collect_expired_requests(self, now: float | None = None) -> list[dict[str, Any]]:
        """Sweeper support: drop and return requests past their TTL."""
        now = time.time() if now is None else now
        expired = [r for r in self.pending_requests.values() if r["expiresAt"] <= now]
        for request in expired:
            self.pending_requests.pop(request["requestId"], None)
        return expired

    # ---- playback (Phase 5, section 11) ----

    def effective_position(self) -> float:
        """D-7: position + elapsed time while playing."""
        state = self.video_state
        if state["play_state"] == "playing":
            return state["position"] + max(0.0, time.monotonic() - state["updated_at"])
        return state["position"]

    def apply_play(self, client_time: float | None) -> dict[str, Any]:
        return self._apply_state("playing", client_time)

    def apply_pause(self, client_time: float | None) -> dict[str, Any]:
        return self._apply_state("paused", client_time)

    def apply_seek(self, client_time: float) -> dict[str, Any]:
        return self._apply_state(self.video_state["play_state"], client_time)

    def apply_change_video(self, video_id: str) -> dict[str, Any]:
        self.video_state["video_id"] = video_id
        self.video_state["position"] = 0.0
        return self._apply_state("paused", 0.0)

    def _apply_state(self, play_state: str, client_time: float | None) -> dict[str, Any]:
        """Set position (client-supplied or effective), stamp state, bump seq."""
        position = self.effective_position() if client_time is None else client_time
        position = max(0.0, min(86400.0, position))
        self.video_state.update(
            {
                "play_state": play_state,
                "position": position,
                "seq": self.video_state["seq"] + 1,
                "updated_at": time.monotonic(),
            }
        )
        return self.state_snapshot()

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

    async def broadcast_to(
        self, event: dict[str, Any], include: set[str]
    ) -> None:
        """Send to a subset (8.3: request_created goes to controllers + requester)."""
        tasks = [
            participant.send(event)
            for user_id, participant in self.participants.items()
            if user_id in include and participant.online
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def __iter__(self) -> Iterator[Participant]:
        return iter(self.participants.values())

    def __len__(self) -> int:
        return len(self.participants)
