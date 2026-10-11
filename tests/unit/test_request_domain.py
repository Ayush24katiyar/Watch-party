"""Approval-request domain unit tests (no DB, no network) - architecture 8.3, R-7, R-9."""

import asyncio
import time

from watch_party.domain.participant import Participant
from watch_party.domain.roles import Role
from watch_party.domain.room import Room


def make_room() -> Room:
    return Room("ABC123", "host-1")


def make_participant(user_id: str, role: Role = Role.PARTICIPANT) -> Participant:
    return Participant(user_id, f"user-{user_id}", role, joined_at=time.time())


def test_create_request_assigns_server_id_and_expiry() -> None:
    room = make_room()
    before = time.time()
    request = room.create_request(make_participant("u1"), "seek", {"time": 30}, 60.0)

    assert request is not None
    assert request["requestId"]
    assert request["user_id"] == "u1"
    assert request["action"] == "seek"
    assert request["payload"] == {"time": 30}
    assert before + 60.0 < request["expiresAt"] <= time.time() + 60.0


def test_request_ids_are_unique() -> None:
    room = make_room()
    ids = {
        room.create_request(make_participant(f"u{i}"), "play", {}, 60.0)["requestId"]
        for i in range(10)
    }

    assert len(ids) == 10


def test_second_pending_request_per_user_is_refused() -> None:
    room = make_room()
    assert room.create_request(make_participant("u1"), "play", {}, 60.0) is not None

    assert room.create_request(make_participant("u1"), "pause", {}, 60.0) is None


def test_room_wide_cap_is_twenty_pending() -> None:
    room = make_room()
    for i in range(20):
        assert room.create_request(make_participant(f"u{i}"), "play", {}, 60.0) is not None

    assert room.create_request(make_participant("u20"), "play", {}, 60.0) is None


def test_get_and_remove_request() -> None:
    room = make_room()
    request = room.create_request(make_participant("u1"), "play", {}, 60.0)

    assert room.get_request(request["requestId"]) == request
    assert room.get_request("no-such-id") is None

    room.remove_request(request["requestId"])
    assert room.get_request(request["requestId"]) is None


def test_remove_unknown_request_is_a_noop() -> None:
    room = make_room()

    room.remove_request("no-such-id")


def test_collect_expired_requests_drops_only_past_ttl() -> None:
    room = make_room()
    room.create_request(make_participant("u1"), "play", {}, 60.0)
    stale = room.create_request(make_participant("u2"), "pause", {}, 60.0)
    stale["expiresAt"] = time.time() - 1.0

    expired = room.collect_expired_requests(now=time.time())

    assert [r["requestId"] for r in expired] == [stale["requestId"]]
    assert room.get_request(stale["requestId"]) is None
    assert len(room.pending_requests) == 1


def test_broadcast_to_reaches_only_included_online() -> None:
    from tests.unit.test_room import FakeConnection

    room = make_room()
    included = Participant("u1", "a", Role.MODERATOR, joined_at=time.time())
    included.connection = FakeConnection()
    excluded = Participant("u2", "b", Role.PARTICIPANT, joined_at=time.time())
    excluded.connection = FakeConnection()
    offline = Participant("u3", "c", Role.HOST, joined_at=time.time())
    offline.connection = None
    room.add(included)
    room.add(excluded)
    room.add(offline)

    asyncio.run(room.broadcast_to({"type": "ping"}, include={"u1", "u3"}))

    assert included.connection.events == [{"type": "ping"}]
    assert excluded.connection.events == []


def test_sanitize_chat_text_strips_controls_trims_and_caps() -> None:
    from watch_party.ws.handlers.chat import sanitize_chat_text

    assert sanitize_chat_text("  hello\x00 world\x7f  ") == "hello world"
    assert sanitize_chat_text("   ") == ""
    assert len(sanitize_chat_text("x" * 600)) == 500
