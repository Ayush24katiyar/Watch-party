"""WebSocket integration tests: Phase 1 foundation + Phase 2 join.

Settings are fast (conftest); each test gets a fresh test DB and RoomManager.
"""

import json
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import (
    TEST_ORIGIN,
    drain_until_close,
    join_payload,
    receive_pings,
    recv_until,
)


def error_code(message: dict) -> str:
    assert message["type"] == "error"
    return message["payload"]["code"]


def joined_event(websocket) -> dict:
    return recv_until(websocket, lambda event: event.get("type") == "room_joined")


# --- Phase 1 cases that do not depend on rooms ---


def test_bad_origin_is_rejected(client) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/DEV", headers={"origin": "http://evil.com"}) as ws:
            ws.receive_text()


def test_missing_origin_rejected_by_default(client) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/DEV") as ws:
            ws.receive_text()


def test_malformed_json_is_error_not_close(client) -> None:
    with client.websocket_connect("/ws/DEV", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_text("{not json")
        assert error_code(ws.receive_json()) == "invalid_message"
        # Still open: no valid join arrives, so the gate closes 4007 after the timeout.
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4007


def test_first_message_must_be_join_room(client) -> None:
    with client.websocket_connect("/ws/DEV", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json({"type": "pong", "payload": {}})
        assert error_code(ws.receive_json()) == "invalid_message"
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4007


def test_silent_socket_closes_with_4007(client) -> None:
    with client.websocket_connect("/ws/DEV", headers={"origin": TEST_ORIGIN}) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4007


# --- Phase 2: identity and join ---


def test_creator_joins_as_host(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"], "ayush"))
        event = joined_event(ws)
        you = event["payload"]["you"]
        assert you["role"] == "host"
        assert you["username"] == "ayush"
        assert event["payload"]["participants"] == [you]
        assert event["payload"]["state"]["playState"] == "paused"
        assert event["payload"]["locked"] is False


def test_second_user_gets_user_joined_broadcast(client, make_user_with_room) -> None:
    host = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        joined_event(ws)

        guest = make_user_with_room()  # second identity, different user
        with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws2:
            ws2.send_json(join_payload(host["roomCode"], guest["userId"], guest["token"], "neha"))
            assert joined_event(ws2)["payload"]["you"]["role"] == "participant"

        # The host hears about the new participant.
        event = recv_until(ws, lambda e: e.get("type") == "user_joined")
        assert event["payload"]["username"] == "neha"
        assert len(event["payload"]["participants"]) == 2


def test_returning_member_keeps_username(client, make_user_with_room) -> None:
    host = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        joined_event(ws)

    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "different-name"))
        you = joined_event(ws)["payload"]["you"]
        assert you["username"] == "ayush"  # stored name kept (10.3)


def test_duplicate_tab_closes_old_socket_with_4004(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"], "ayush"))
        joined_event(ws)

        with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws2:
            ws2.send_json(join_payload(user["roomCode"], user["userId"], user["token"], "ayush"))
            assert joined_event(ws2)["payload"]["you"]["role"] == "host"
            with pytest.raises(WebSocketDisconnect) as exc:
                drain_until_close(ws)
        assert exc.value.code == 4004


def test_bad_token_closes_4002(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_text(json.dumps(join_payload(user["roomCode"], user["userId"], "wrong-token")))
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4002


def test_unknown_user_closes_4002(client, make_user_with_room) -> None:
    user = make_user_with_room()
    payload = join_payload(user["roomCode"], str(uuid4()), "whatever-token")
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_text(json.dumps(payload))
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4002


def test_unknown_room_closes_4001(client, make_user_with_room) -> None:
    user = make_user_with_room()
    payload = join_payload("NOSUCH", user["userId"], user["token"])
    with client.websocket_connect("/ws/NOSUCH", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_text(json.dumps(payload))
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4001


def test_closed_room_is_reported_like_missing(client, make_user_with_room, room_ops) -> None:
    user = make_user_with_room()
    room_ops["set_status"](user["roomCode"], "closed")
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"]))
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4001


def test_locked_room_closes_4006_for_new_member(client, make_user_with_room, room_ops) -> None:
    host = make_user_with_room()
    room_ops["set_status"](host["roomCode"], "locked")
    guest = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], guest["userId"], guest["token"], "neha"))
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4006


def test_banned_member_closes_4003(client, make_user_with_room, room_ops) -> None:
    host = make_user_with_room()
    room_ops["ban"](host["roomCode"], host["userId"])
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4003


def test_lowercase_code_joins(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode'].lower()}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"].lower(), user["userId"], user["token"], "ayush"))
        event = joined_event(ws)
        assert event["payload"]["you"]["role"] == "host"


def test_full_room_closes_4005(client, make_user_with_room, monkeypatch) -> None:
    from watch_party.config import get_settings

    monkeypatch.setenv("MAX_ROOM_SIZE", "2")
    get_settings.cache_clear()
    host = make_user_with_room()
    guest = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        joined_event(ws)
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], guest["userId"], guest["token"], "neha"))
        joined_event(ws)

    third = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], third["userId"], third["token"], "raj"))
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4005


# --- Phase 1 limits, still valid after join ---


def test_oversized_message_closes_with_4007(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"]))
        joined_event(ws)
        # Over WS_MAX_SIZE_BYTES (1024 in tests); the size check runs before parsing.
        ws.send_text(json.dumps({"type": "pong", "payload": {"blob": "x" * 2000}}))
        assert error_code(recv_until(ws, lambda e: e.get("type") == "error")) == "invalid_message"
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
    assert exc.value.code == 4007


def test_rate_limited_burst_gets_error(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"]))
        joined_event(ws)
        # Bucket is 5/s; join already spent one token, so a burst must trip the limit.
        for _ in range(12):
            ws.send_json({"type": "pong", "payload": {}})
        assert error_code(recv_until(ws, lambda e: e.get("type") == "error")) == "rate_limited"


def test_unknown_type_after_join_is_error(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"]))
        joined_event(ws)
        ws.send_json({"type": "dance", "payload": {}})
        assert error_code(recv_until(ws, lambda e: e.get("type") == "error")) == "invalid_message"
        # Still processing: another unknown type gets the same treatment.
        ws.send_json({"type": "nonsense", "payload": {}})
        assert error_code(recv_until(ws, lambda e: e.get("type") == "error")) == "invalid_message"


def test_error_includes_request_id(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"]))
        joined_event(ws)
        ws.send_json({"type": "seek", "payload": {"time": -1}, "requestId": "req-1"})
        message = recv_until(ws, lambda e: e.get("type") == "error")
        assert message["payload"]["code"] == "invalid_message"
        assert message["payload"]["requestId"] == "req-1"


def test_ping_pong_keeps_connection_alive(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"]))
        joined_event(ws)
        receive_pings(ws, 3)
        # Still processing messages after the heartbeat exchange.
        ws.send_json({"type": "nonsense", "payload": {}})
        assert error_code(recv_until(ws, lambda e: e.get("type") == "error")) == "invalid_message"


def test_concurrent_joins_both_succeed(client, make_user_with_room) -> None:
    """Two users joining without waiting for each other's replies (D-13 lock)."""
    host = make_user_with_room()
    guest = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws2:
            ws2.send_json(join_payload(host["roomCode"], guest["userId"], guest["token"], "neha"))
            # Both sends happen before either reply is read.
            you = joined_event(ws2)["payload"]["you"]
            assert you["username"] == "neha"
            assert you["role"] == "participant"
        host_event = joined_event(ws)
        assert host_event["payload"]["you"]["role"] == "host"


def test_zombie_connection_closes_with_1001(client, make_user_with_room) -> None:
    user = make_user_with_room()
    with client.websocket_connect(f"/ws/{user['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(user["roomCode"], user["userId"], user["token"]))
        joined_event(ws)
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_text()  # pings arrive but are never answered
    assert exc.value.code == 1001
