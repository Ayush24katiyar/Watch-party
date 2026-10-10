"""RoomManager: code -> Room registry (architecture section 7).

Rooms live in this process's memory (D-11: exactly one worker). Restores rooms
from the database when they are missing from memory (10.1, D-22).
"""

import uuid
from typing import Any

from watch_party.domain.participant import Participant
from watch_party.domain.room import Room
from watch_party.domain.roles import Role


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}

    @staticmethod
    def normalize(code: str) -> str:
        return code.strip().upper()

    def get(self, code: str) -> Room | None:
        return self._rooms.get(self.normalize(code))

    def register(self, room: Room) -> Room:
        self._rooms[room.code] = room
        return room

    def forget(self, code: str) -> None:
        self._rooms.pop(self.normalize(code), None)

    def build_from_snapshot(
        self,
        code: str,
        host_user_id: str,
        status: str,
        members: list[dict[str, Any]],
        video_state: dict[str, Any] | None = None,
        db_id: uuid.UUID | None = None,
    ) -> Room:
        """Lazy restore (D-22): members come back offline with stored roles;
        playback restores as paused because downtime is unmeasurable."""
        room = Room(
            code=code,
            host_user_id=host_user_id,
            locked=status == "locked",
            db_id=db_id,
        )
        if video_state:
            room.video_state.update(video_state)
        room.video_state["play_state"] = "paused"
        for member in members:
            room.add(
                Participant(
                    user_id=str(member["user_id"]),
                    username=member["username"],
                    role=Role(member["role"]),
                    joined_at=float(member.get("joined_ts", 0.0)),
                )
            )
        return self.register(room)

    def reset(self) -> None:
        """Test hook: drop all in-memory rooms between integration tests."""
        self._rooms.clear()


# Module-level singleton, matching the single-process design (D-11).
room_manager = RoomManager()
