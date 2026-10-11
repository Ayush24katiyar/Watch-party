"""Room unit tests with fake sockets (no DB, no network) - architecture 18.1."""

import asyncio
import time
from unittest.mock import patch

from watch_party.domain.participant import Participant
from watch_party.domain.roles import Role
from watch_party.domain.room import Room


class FakeConnection:
    """Stands in for the WebSocket connection; records what was sent."""

    def __init__(self, delay: float = 0.0) -> None:
        self.events: list[dict] = []
        self.delay = delay

    async def send(self, event: dict) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.events.append(event)


def make_participant(user_id: str, username: str, role: Role = Role.PARTICIPANT) -> Participant:
    participant = Participant(user_id, username, role)
    participant.connection = FakeConnection()
    return participant


def test_broadcast_reaches_all_online_participants() -> None:
    room = Room("ABC123", "host-1")
    a = make_participant("u1", "a")
    b = make_participant("u2", "b")
    room.add(a)
    room.add(b)

    asyncio.run(room.broadcast({"type": "ping"}))

    assert a.connection.events == [{"type": "ping"}]
    assert b.connection.events == [{"type": "ping"}]


def test_broadcast_can_exclude_one_participant() -> None:
    room = Room("ABC123", "host-1")
    a = make_participant("u1", "a")
    b = make_participant("u2", "b")
    room.add(a)
    room.add(b)

    asyncio.run(room.broadcast({"type": "user_joined"}, exclude_user_id="u1"))

    assert a.connection.events == []
    assert len(b.connection.events) == 1


def test_broadcast_skips_offline_participants() -> None:
    room = Room("ABC123", "host-1")
    online = make_participant("u1", "a")
    offline = make_participant("u2", "b")
    offline.connection = None
    room.add(online)
    room.add(offline)

    asyncio.run(room.broadcast({"type": "ping"}))

    assert len(online.connection.events) == 1


def test_slow_participant_does_not_block_the_room() -> None:
    room = Room("ABC123", "host-1")
    fast = make_participant("u1", "fast")
    slow = make_participant("u2", "slow")

    async def _timeout(event: dict) -> None:
        raise TimeoutError("simulated slow-client timeout")

    slow.connection.send = _timeout  # type: ignore[method-assign]
    room.add(fast)
    room.add(slow)

    started = time.monotonic()
    asyncio.run(room.broadcast({"type": "ping"}))
    elapsed = time.monotonic() - started

    assert fast.connection.events == [{"type": "ping"}]
    assert elapsed < 1.0


def test_remove_returns_the_participant_and_frees_the_seat() -> None:
    room = Room("ABC123", "host-1")
    a = make_participant("u1", "a", Role.HOST)
    room.add(a)
    assert room.is_full(1)

    removed = room.remove("u1")

    assert removed is a
    assert "u1" not in room.participants
    assert not room.is_full(1)


def test_has_online_participants_tracks_connections() -> None:
    room = Room("ABC123", "host-1")
    participant = make_participant("u1", "a")
    room.add(participant)

    assert room.has_online_participants()
    participant.connection = None
    assert not room.has_online_participants()


def test_state_snapshot_effective_position() -> None:
    room = Room("ABC123", "host-1")
    with patch("watch_party.domain.room.time.monotonic", return_value=1000.0):
        room.video_state = {
            "video_id": "abcdefghijk",
            "play_state": "playing",
            "position": 10.0,
            "seq": 3,
            "updated_at": 999.5,
        }

        snapshot = room.state_snapshot()

    assert snapshot["videoId"] == "abcdefghijk"
    assert snapshot["playState"] == "playing"
    assert snapshot["seq"] == 3
    assert snapshot["currentTime"] == 10.5


def test_state_snapshot_paused_does_not_advance() -> None:
    room = Room("ABC123", "host-1")
    room.video_state = {
        "video_id": None,
        "play_state": "paused",
        "position": 7.5,
        "seq": 1,
        "updated_at": time.monotonic() - 10.0,
    }

    assert room.state_snapshot()["currentTime"] == 7.5


def test_participant_snapshot_wire_shape() -> None:
    participant = make_participant("u1", "a", Role.MODERATOR)

    assert participant.snapshot() == {
        "userId": "u1",
        "username": "a",
        "role": "moderator",
        "online": True,
    }
