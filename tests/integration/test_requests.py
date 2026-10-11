"""Phase 6 integration tests: approval requests (architecture 8.2, 8.3, R-7, R-9).

One hard rule per test, driven through real WebSocket clients.
"""

import time

from tests.conftest import TEST_ORIGIN, error_of, join_payload, recv_until


def _request_id_of_host(ws_host, action: str, payload: dict) -> str:
    """Guest requests; return the requestId from the host's `request_created`."""
    created = recv_until(ws_host, lambda e: e.get("type") == "request_created")["payload"]
    assert created["action"] == action
    assert created["payload"] == payload
    return created["requestId"]


def _events_until(ws, barrier_type: str, timeout: float = 5.0) -> list[dict]:
    """Non-ping events seen on `ws` before the first `barrier_type` event."""
    from tests.conftest import receive_json_bounded

    seen: list[dict] = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"barrier {barrier_type} never arrived; saw: {[e.get('type') for e in seen]}")
        event = receive_json_bounded(ws, timeout=min(timeout, remaining))
        if event.get("type") == "ping":
            ws.send_json({"type": "pong", "payload": {}})
            continue
        if event.get("type") == barrier_type:
            return seen
        seen.append(event)


def test_participant_request_reaches_host_with_spec_shape(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("request_action", {"action": "play", "payload": {}})
        created = recv_until(room.ws_host, lambda e: e.get("type") == "request_created")["payload"]
        assert set(created) == {"requestId", "userId", "username", "action", "payload", "expiresAt"}
        assert created["userId"] == room.guest["userId"]
        assert created["username"] == "neha"
        assert created["action"] == "play"
        assert created["payload"] == {}


def test_host_request_action_is_forbidden(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("request_action", {"action": "play", "payload": {}})
        assert error_of(room.ws_host)["code"] == "forbidden"


def test_moderator_request_action_is_forbidden(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("assign_role", {"userId": room.guest["userId"], "role": "moderator"})
        recv_until(room.ws_guest, lambda e: e.get("type") == "role_assigned")
        room.send_guest("request_action", {"action": "play", "payload": {}})
        assert error_of(room.ws_guest)["code"] == "forbidden"


def test_non_requester_gets_no_request_created(client, joined_pair, make_user_with_room) -> None:
    outsider = make_user_with_room()
    with joined_pair as room, client.websocket_connect(
        f"/ws/{room.code}", headers={"origin": TEST_ORIGIN}
    ) as ws_out:
        ws_out.send_json(
            join_payload(room.code, outsider["userId"], outsider["token"], "raj")
        )
        recv_until(ws_out, lambda e: e.get("type") == "room_joined")
        room.send_guest("request_action", {"action": "play", "payload": {}})
        # Barrier every member must receive: the outsider sees sync_state
        # only after proving no request_created came first.
        room.send_host("play", {})
        seen = _events_until(ws_out, "sync_state")
        assert [e.get("type") for e in seen if e.get("type") == "request_created"] == []


def test_second_pending_request_same_user_is_conflict(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("request_action", {"action": "play", "payload": {}})
        recv_until(room.ws_host, lambda e: e.get("type") == "request_created")
        room.send_guest("request_action", {"action": "pause", "payload": {}})
        assert error_of(room.ws_guest)["code"] == "conflict"


def test_approve_applies_state_and_resolves(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("request_action", {"action": "play", "payload": {}})
        request_id = _request_id_of_host(room.ws_host, "play", {})
        room.send_host("resolve_request", {"requestId": request_id, "approve": True})

        host_state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        guest_state = recv_until(room.ws_guest, lambda e: e.get("type") == "sync_state")["payload"]
        assert host_state == guest_state
        assert host_state["playState"] == "playing"
        assert host_state["seq"] == 1

        resolved = recv_until(room.ws_host, lambda e: e.get("type") == "request_resolved")["payload"]
        assert resolved["requestId"] == request_id
        assert resolved["approved"] is True


def test_moderator_approve_applies(client, joined_pair, make_user_with_room) -> None:
    outsider = make_user_with_room()
    with joined_pair as room:
        room.send_host("assign_role", {"userId": room.guest["userId"], "role": "moderator"})
        recv_until(room.ws_guest, lambda e: e.get("type") == "role_assigned")
        with client.websocket_connect(
            f"/ws/{room.code}", headers={"origin": TEST_ORIGIN}
        ) as ws_out:
            ws_out.send_json(
                join_payload(room.code, outsider["userId"], outsider["token"], "raj")
            )
            recv_until(ws_out, lambda e: e.get("type") == "room_joined")
            ws_out.send_json({"type": "request_action", "payload": {"action": "play", "payload": {}}})
            created = recv_until(
                room.ws_guest, lambda e: e.get("type") == "request_created"
            )["payload"]
            room.send_guest(
                "resolve_request", {"requestId": created["requestId"], "approve": True}
            )
            state = recv_until(ws_out, lambda e: e.get("type") == "sync_state")["payload"]
            assert state["playState"] == "playing"
            assert state["seq"] == 1


def test_reject_changes_nothing(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("request_action", {"action": "seek", "payload": {"time": 30}})
        request_id = _request_id_of_host(room.ws_host, "seek", {"time": 30})
        room.send_host("resolve_request", {"requestId": request_id, "approve": False})

        resolved = recv_until(room.ws_host, lambda e: e.get("type") == "request_resolved")["payload"]
        assert resolved["approved"] is False
        # Nothing was applied: the next real action is still seq 1.
        room.send_host("play", {})
        state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["seq"] == 1


def test_approve_applies_requested_seek(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("request_action", {"action": "seek", "payload": {"time": 30}})
        request_id = _request_id_of_host(room.ws_host, "seek", {"time": 30})
        room.send_host("resolve_request", {"requestId": request_id, "approve": True})

        state = recv_until(room.ws_guest, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["currentTime"] == 30
        assert state["seq"] == 1


def test_resolve_unknown_id_is_expired(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("resolve_request", {"requestId": "no-such-request", "approve": True})
        assert error_of(room.ws_host)["code"] == "request_expired"


def test_participant_resolve_is_forbidden(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("request_action", {"action": "play", "payload": {}})
        request_id = _request_id_of_host(room.ws_host, "play", {})
        room.send_guest("resolve_request", {"requestId": request_id, "approve": True})
        assert error_of(room.ws_guest)["code"] == "forbidden"


def test_approve_after_kick_is_expired(client, joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("request_action", {"action": "play", "payload": {}})
        request_id = _request_id_of_host(room.ws_host, "play", {})
        room.send_host("remove_participant", {"userId": room.guest["userId"]})
        recv_until(room.ws_guest, lambda e: e.get("type") == "participant_removed")
        room.send_host("resolve_request", {"requestId": request_id, "approve": True})
        assert error_of(room.ws_host)["code"] == "request_expired"


def test_request_action_payload_validation(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest("request_action", {"action": "dance", "payload": {}})
        assert error_of(room.ws_guest)["code"] == "invalid_message"
        room.send_guest("request_action", {"payload": {}})
        assert error_of(room.ws_guest)["code"] == "invalid_message"
        # Connection stays open: a valid request works right after.
        room.send_guest("request_action", {"action": "play", "payload": {}})
        recv_until(room.ws_host, lambda e: e.get("type") == "request_created")


def test_resolve_payload_validation(joined_pair) -> None:
    with joined_pair as room:
        room.send_host("resolve_request", {"payload": {}})
        assert error_of(room.ws_host)["code"] == "invalid_message"
        room.send_host("resolve_request", {"requestId": "x"})
        assert error_of(room.ws_host)["code"] == "invalid_message"
        # Connection stays open.
        room.send_host("play", {})
        state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["seq"] == 1


def test_malformed_inner_payload_is_rejected_up_front(joined_pair) -> None:
    """B-021: the inner payload must satisfy the real action schema (8.2).

    A `seek` with no `time` is rejected when the request is created, so it can
    never reach `apply_seek` and crash the approver with a KeyError.
    """
    with joined_pair as room:
        room.send_guest("request_action", {"action": "seek", "payload": {}})
        assert error_of(room.ws_guest)["code"] == "invalid_message"

        # No request was created, and both sockets are still usable.
        room.send_host("play", {})
        assert recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")


def test_malformed_change_video_payload_is_rejected(joined_pair) -> None:
    with joined_pair as room:
        room.send_guest(
            "request_action", {"action": "change_video", "payload": {"videoId": "not-valid"}}
        )
        assert error_of(room.ws_guest)["code"] == "invalid_message"


def test_pending_requests_replay_shape(client, joined_pair, make_user_with_room) -> None:
    latecomer = make_user_with_room()
    with joined_pair as room:
        room.send_guest("request_action", {"action": "play", "payload": {}})
        recv_until(room.ws_host, lambda e: e.get("type") == "request_created")
        with client.websocket_connect(
            f"/ws/{room.code}", headers={"origin": TEST_ORIGIN}
        ) as ws_late:
            ws_late.send_json(
                join_payload(room.code, latecomer["userId"], latecomer["token"], "raj")
            )
            joined = recv_until(ws_late, lambda e: e.get("type") == "room_joined")["payload"]
            assert joined["pendingRequests"][0]["userId"] == room.guest["userId"]


def test_expired_request_sweeper_broadcasts(client, make_user_with_room, monkeypatch) -> None:
    from watch_party.config import get_settings

    monkeypatch.setenv("REQUEST_TTL_SECONDS", "0.3")
    monkeypatch.setenv("REQUEST_SWEEP_SECONDS", "0.2")
    get_settings.cache_clear()
    host = make_user_with_room()
    guest = make_user_with_room()
    with client.websocket_connect(
        f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}
    ) as ws_host:
        ws_host.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws_host, lambda e: e.get("type") == "room_joined")
        with client.websocket_connect(
            f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}
        ) as ws_guest:
            ws_guest.send_json(
                join_payload(host["roomCode"], guest["userId"], guest["token"], "neha")
            )
            recv_until(ws_guest, lambda e: e.get("type") == "room_joined")
            ws_guest.send_json({"type": "request_action", "payload": {"action": "play", "payload": {}}})
            recv_until(ws_host, lambda e: e.get("type") == "request_created")

            # One bounded wait that answers pings throughout: a blind sleep
            # gap would starve pongs and earn a 1001 zombie close.
            event = recv_until(
                ws_host, lambda e: e.get("type") == "request_resolved", timeout=10.0
            )
            assert event["payload"].get("reason") == "expired"
