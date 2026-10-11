"""RoomManager: code -> Room registry (architecture section 7).

Rooms live in this process's memory (D-11: exactly one worker). Restores rooms
from the database when they are missing from memory (10.1, D-22). Also holds the
empty-room cleanup timers (10.5); the DB write on expiry is injected as a
callback so this class stays database-free (doc rule 4).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from watch_party.domain.participant import Participant
from watch_party.domain.roles import Role
from watch_party.domain.room import Room

if TYPE_CHECKING:
    from watch_party.ws.endpoint import Connection

# Called when an empty room's timer expires: (room) -> None.
RoomExpiredCallback = Callable[[Room], Awaitable[None]]


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._restore_locks: dict[str, asyncio.Lock] = {}
        self._connections: set[Connection] = set()
        self._cleanup_tasks: dict[str, asyncio.Task[None]] = {}
        self._host_grace_tasks: dict[str, asyncio.Task[None]] = {}
        self._snapshot_tasks: dict[str, asyncio.Task[None]] = {}

    def register_connection(self, connection: "Connection") -> None:
        self._connections.add(connection)

    def unregister_connection(self, connection: "Connection") -> None:
        self._connections.discard(connection)

    def all_connections(self) -> list["Connection"]:
        return list(self._connections)

    @staticmethod
    def normalize(code: str) -> str:
        return code.strip().upper()

    def get(self, code: str) -> Room | None:
        return self._rooms.get(self.normalize(code))

    def all_rooms(self) -> list[Room]:
        return list(self._rooms.values())

    def restore_lock(self, code: str) -> asyncio.Lock:
        """One lock per room code, so two simultaneous joins cannot both miss
        the memory cache and each register a fresh Room (B-010)."""
        key = self.normalize(code)
        lock = self._restore_locks.get(key)
        if lock is None:
            lock = self._restore_locks.setdefault(key, asyncio.Lock())
        return lock

    def register(self, room: Room) -> Room:
        self._rooms[room.code] = room
        return room

    def forget(self, code: str) -> None:
        self._rooms.pop(self.normalize(code), None)
        self._restore_locks.pop(self.normalize(code), None)

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

    # ---- empty-room cleanup (10.5) ----

    def schedule_cleanup(
        self, room: Room, ttl_seconds: float, on_expired: RoomExpiredCallback
    ) -> None:
        """Start (or restart) the empty-room timer; cancelled when someone joins."""
        self.cancel_cleanup(room)
        task = asyncio.create_task(self._close_when_empty(room, ttl_seconds, on_expired))
        self._cleanup_tasks[room.code] = task

    def cancel_cleanup(self, room: Room) -> None:
        task = self._cleanup_tasks.pop(room.code, None)
        if task is not None:
            task.cancel()

    # ---- host grace (D-15, 10.3) ----

    def schedule_host_grace(
        self, room: Room, grace_seconds: float, on_expired: RoomExpiredCallback
    ) -> None:
        """Start (or restart) the host-reconnect window; cancelled when the host returns."""
        self.cancel_host_grace(room)
        task = asyncio.create_task(self._expire_room_later(room, grace_seconds, on_expired))
        self._host_grace_tasks[room.code] = task

    def cancel_host_grace(self, room: Room) -> None:
        task = self._host_grace_tasks.pop(room.code, None)
        if task is not None:
            task.cancel()

    # ---- debounced playback snapshots (D-22) ----

    def schedule_snapshot(
        self, room: Room, debounce_seconds: float, on_snapshot: RoomExpiredCallback
    ) -> None:
        """Write the playback snapshot to the DB, debounced so rapid changes
        coalesce into one write per window."""
        self.cancel_snapshot(room)
        task = asyncio.create_task(self._expire_room_later(room, debounce_seconds, on_snapshot))
        self._snapshot_tasks[room.code] = task

    def cancel_snapshot(self, room: Room) -> None:
        task = self._snapshot_tasks.pop(room.code, None)
        if task is not None:
            task.cancel()

    async def _close_when_empty(
        self, room: Room, ttl_seconds: float, on_expired: RoomExpiredCallback
    ) -> None:
        """Empty-room cleanup (10.5): only close if nobody is still connected."""
        try:
            await asyncio.sleep(ttl_seconds)
        except asyncio.CancelledError:
            return
        if room.has_online_participants():
            return  # someone rejoined before expiry
        await on_expired(room)

    async def _expire_room_later(
        self, room: Room, ttl_seconds: float, on_expired: RoomExpiredCallback
    ) -> None:
        """Sleep, then fire the callback unconditionally.

        Deliberately has no "is anyone online" check. The three timers have
        different rules and must not share one guard (B-015):
          - empty-room cleanup  -> uses _close_when_empty instead;
          - host grace (D-15)   -> must fire even while guests are online,
            otherwise a host who drops silently is never replaced;
          - playback snapshot   -> must always be written, otherwise state is
            never persisted while anybody is watching.
        """
        try:
            await asyncio.sleep(ttl_seconds)
            await on_expired(room)
        except asyncio.CancelledError:
            pass

    def reset(self) -> None:
        """Test hook: drop all in-memory rooms and cancel cleanup timers."""
        for task in self._cleanup_tasks.values():
            task.cancel()
        self._cleanup_tasks.clear()
        for task in self._host_grace_tasks.values():
            task.cancel()
        self._host_grace_tasks.clear()
        for task in self._snapshot_tasks.values():
            task.cancel()
        self._snapshot_tasks.clear()
        self._connections.clear()
        self._rooms.clear()
        self._restore_locks.clear()


# Module-level singleton, matching the single-process design (D-11).
room_manager = RoomManager()
