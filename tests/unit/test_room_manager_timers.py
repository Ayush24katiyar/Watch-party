"""RoomManager timer semantics (architecture 10.3, 10.5, D-15, D-22).

Each timer has a different expiry rule. Sharing one guard between them broke
two of them (B-015 plus snapshot persistence), so the rules are pinned here.
"""

import asyncio

from watch_party.domain.room import Room
from watch_party.domain.room_manager import RoomManager


def _run_with_timer(manager: RoomManager, schedule, fired: list[str]) -> None:
    """Schedule a timer and let it expire on the SAME event loop.

    The manager creates an asyncio.Task, so the sleep has to happen inside the
    loop that created it; a separate asyncio.run() would use a different loop.
    """

    async def scenario() -> None:
        schedule()
        await asyncio.sleep(0.1)

    asyncio.run(scenario())


def _room_with_online_guest() -> Room:
    """A room with one participant holding a connection (i.e. someone online)."""
    room = Room("ABC123", "host-1")
    guest = _connected_participant("u2", "guest")
    room.add(guest)
    assert room.has_online_participants()
    return room


def _connected_participant(user_id: str, username: str):
    from watch_party.domain.participant import Participant
    from watch_party.domain.roles import Role

    participant = Participant(user_id, username, Role.PARTICIPANT)

    class _Conn:
        async def send(self, event: dict) -> None:
            pass

    participant.connection = _Conn()
    return participant


def test_snapshot_is_written_while_participants_are_online() -> None:
    """D-22: the debounced snapshot must fire even when the room is busy.

    Regression: the shared guard skipped the write whenever anybody was online,
    so playback state was never persisted during normal use.
    """
    manager = RoomManager()
    room = _room_with_online_guest()
    fired: list[str] = []

    async def on_snapshot(_room: Room) -> None:
        fired.append("snapshot")

    _run_with_timer(
        manager, lambda: manager.schedule_snapshot(room, 0.01, on_snapshot), fired
    )

    assert fired == ["snapshot"]


def test_host_grace_fires_while_a_guest_is_still_online() -> None:
    """D-15: a host who drops must be replaced even if guests remain."""
    manager = RoomManager()
    room = _room_with_online_guest()
    fired: list[str] = []

    async def on_grace(_room: Room) -> None:
        fired.append("grace")

    _run_with_timer(
        manager, lambda: manager.schedule_host_grace(room, 0.01, on_grace), fired
    )

    assert fired == ["grace"]


def test_empty_room_cleanup_skipped_while_someone_is_online() -> None:
    """10.5: the room must not close out from under a connected member."""
    manager = RoomManager()
    room = _room_with_online_guest()
    fired: list[str] = []

    async def on_expired(_room: Room) -> None:
        fired.append("closed")

    _run_with_timer(
        manager, lambda: manager.schedule_cleanup(room, 0.01, on_expired), fired
    )

    assert fired == []


def test_empty_room_cleanup_fires_when_nobody_is_online() -> None:
    manager = RoomManager()
    room = Room("ABC123", "host-1")
    assert not room.has_online_participants()
    fired: list[str] = []

    async def on_expired(_room: Room) -> None:
        fired.append("closed")

    _run_with_timer(
        manager, lambda: manager.schedule_cleanup(room, 0.01, on_expired), fired
    )

    assert fired == ["closed"]


def test_restore_lock_is_shared_per_code_and_not_across_codes() -> None:
    """B-010: concurrent restores of one code must serialize."""
    manager = RoomManager()
    assert manager.restore_lock("abc123") is manager.restore_lock("ABC123")
    assert manager.restore_lock("abc123") is not manager.restore_lock("xyz789")


def test_forget_drops_the_restore_lock() -> None:
    manager = RoomManager()
    manager.restore_lock("abc123")
    manager.forget("abc123")
    assert manager.restore_lock("abc123") is not None