"""Phase 4 integration tests: roles and host tools (architecture section 9).

Each test drives real WebSocket clients through one hard rule from section 9.
"""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import (
    TEST_ORIGIN,
    drain_until_close,
    error_of,
    join_payload,
    participant_by_id,
    recv_until,
    wait_until,
)

# --- section 9 hard rules ---


def test_participant_cannot_assign_role(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("assign_role", {"userId": room.host["userId"], "role": "moderator"})
        assert error_of(room.ws_guest)["code"] == "forbidden"


def test_moderator_cannot_assign_role(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("assign_role", {"userId": room.guest["userId"], "role": "moderator"})
        recv_until(room.ws_guest, lambda e: e.get("type") == "role_assigned")
        room.send_guest("assign_role", {"userId": room.host["userId"], "role": "participant"})
        assert error_of(room.ws_guest)["code"] == "forbidden"


def test_assign_role_cannot_target_host(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("assign_role", {"userId": room.host["userId"], "role": "moderator"})
        assert error_of(room.ws_host)["code"] == "forbidden"


@pytest.mark.spec_question(
    reason="spec says role must be moderator/participant not host, but names no error code; schema layer rejects first"
)
def test_assign_role_cannot_assign_host(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("assign_role", {"userId": room.guest["userId"], "role": "host"})
        assert error_of(room.ws_host)["code"] == "invalid_message"


def test_assign_role_to_unknown_user_is_not_found(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("assign_role", {"userId": "nobody", "role": "moderator"})
        assert error_of(room.ws_host)["code"] == "not_found"


def test_assign_role_broadcasts_to_everyone(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("assign_role", {"userId": room.guest["userId"], "role": "moderator"})
        event = recv_until(room.ws_guest, lambda e: e.get("type") == "role_assigned")
        assert event["payload"]["role"] == "moderator"
        assert participant_by_id(event["payload"]["participants"], room.guest["userId"])["role"] == "moderator"


def test_removed_participant_gets_4003_and_cannot_rejoin(client, joined_pair) -> None:
    with joined_pair as room:
        room.send_host("remove_participant", {"userId": room.guest["userId"]})
        event = recv_until(room.ws_guest, lambda e: e.get("type") == "participant_removed")
        assert event["payload"]["userId"] == room.guest["userId"]
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(room.ws_guest)
        assert exc.value.code == 4003

    # Banned: rejoining is refused with 4003 (D-16).
    with client.websocket_connect(f"/ws/{room.code}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(room.code, room.guest["userId"], room.guest["token"], "neha"))
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4003


def test_transfer_host_requires_online_target(client, make_user_with_room) -> None:
    host = make_user_with_room()
    guest = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")
        with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws_guest:
            ws_guest.send_json(join_payload(host["roomCode"], guest["userId"], guest["token"], "neha"))
            recv_until(ws_guest, lambda e: e.get("type") == "room_joined")
            # Intentional leave: server-side departure is deterministic, unlike
            # socket exit (which can race TestClient teardown). Guest stays a
            # member but goes offline.
            ws_guest.send_json({"type": "leave_room", "payload": {"roomId": host["roomCode"]}})
            with pytest.raises(WebSocketDisconnect) as exc:
                drain_until_close(ws_guest)
            assert exc.value.code == 1000
        # Guest is an offline member now -> transfer is refused.
        ws.send_json({"type": "transfer_host", "payload": {"userId": guest["userId"]}})
        assert error_of(ws)["code"] == "conflict"


def test_transfer_host_swaps_roles(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("transfer_host", {"userId": room.guest["userId"]})
        event = recv_until(room.ws_host, lambda e: e.get("type") == "host_transferred")
        assert event["payload"]["oldHostId"] == room.host["userId"]
        assert event["payload"]["newHostId"] == room.guest["userId"]
        assert (
            participant_by_id(event["payload"]["participants"], room.host["userId"])["role"]
            == "moderator"
        )  # old host becomes Moderator (8.2)


def test_transfer_host_to_self_is_forbidden(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("transfer_host", {"userId": room.host["userId"]})
        assert error_of(room.ws_host)["code"] == "forbidden"


def test_lock_room_blocks_new_members(client, joined_pair, make_user_with_room) -> None:
    with joined_pair as room:
        room.send_host("lock_room", {"locked": True})
        event = recv_until(room.ws_guest, lambda e: e.get("type") == "room_locked")
        assert event["payload"]["locked"] is True

        newcomer = make_user_with_room()
        with client.websocket_connect(f"/ws/{room.code}", headers={"origin": TEST_ORIGIN}) as ws:
            ws.send_json(join_payload(room.code, newcomer["userId"], newcomer["token"], "raj"))
            with pytest.raises(WebSocketDisconnect) as exc:
                drain_until_close(ws)
        assert exc.value.code == 4006

        # Unlocking lets newcomers in again.
        room.send_host("lock_room", {"locked": False})
        recv_until(room.ws_guest, lambda e: e.get("type") == "room_locked")
        with client.websocket_connect(f"/ws/{room.code}", headers={"origin": TEST_ORIGIN}) as ws:
            ws.send_json(join_payload(room.code, newcomer["userId"], newcomer["token"], "raj"))
            assert recv_until(ws, lambda e: e.get("type") == "room_joined")


def test_intentional_host_leave_reassigns_immediately(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("leave_room", {"roomId": room.code})
        event = recv_until(room.ws_guest, lambda e: e.get("type") == "host_transferred")
        assert event["payload"]["newHostId"] == room.guest["userId"]
        assert (
            participant_by_id(event["payload"]["participants"], room.guest["userId"])["role"]
            == "host"
        )


def test_host_disconnect_waits_for_grace_then_reassigns(
    client, make_user_with_room, monkeypatch
) -> None:
    from contextlib import ExitStack

    from watch_party.config import get_settings

    monkeypatch.setenv("HOST_GRACE_SECONDS", "0.3")
    get_settings.cache_clear()
    host = make_user_with_room()
    guest = make_user_with_room()

    with ExitStack() as stack:
        ws_host = stack.enter_context(
            client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN})
        )
        ws_host.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws_host, lambda e: e.get("type") == "room_joined")
        ws_guest = stack.enter_context(
            client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN})
        )
        ws_guest.send_json(join_payload(host["roomCode"], guest["userId"], guest["token"], "neha"))
        recv_until(ws_guest, lambda e: e.get("type") == "room_joined")
        # Host tab closes while the guest stays online to witness events.
        ws_host.close()
        # Departure is announced...
        event = recv_until(ws_guest, lambda e: e.get("type") == "user_left")
        assert event["payload"]["userId"] == host["userId"]
        # ...then the grace expires and the guest is promoted (D-15).
        event = recv_until(ws_guest, lambda e: e.get("type") == "host_transferred")
        assert event["payload"]["newHostId"] == guest["userId"]


def test_host_reconnect_within_grace_keeps_host(client, make_user_with_room, monkeypatch) -> None:
    from watch_party.config import get_settings

    monkeypatch.setenv("HOST_GRACE_SECONDS", "0.6")
    get_settings.cache_clear()
    host = make_user_with_room()

    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")

    # Reconnect inside the grace window (D-15).
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        joined = recv_until(ws, lambda e: e.get("type") == "room_joined")
        assert joined["payload"]["you"]["role"] == "host"

    # Past the grace window: no reassignment happened, the host kept the role.
    start = time.monotonic()
    wait_until(lambda: time.monotonic() > start + 0.8, timeout=5.0)

    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        joined = recv_until(ws, lambda e: e.get("type") == "room_joined")
        assert joined["payload"]["you"]["role"] == "host"
