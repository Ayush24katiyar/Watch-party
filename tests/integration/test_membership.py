"""Phase 3 integration tests: membership lifecycle (architecture 16, 10.3, 10.5)."""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import (
    TEST_ORIGIN,
    drain_until_close,
    join_payload,
    participant_by_id,
    recv_until,
    wait_until,
)


def test_leave_room_broadcasts_user_left_and_closes(client, joined_pair) -> None:
    with joined_pair as pair:
        pair.ws_host.send_json({"type": "leave_room", "payload": {"roomId": pair.host["roomCode"]}})

        # The guest hears about the departure with the updated list.
        event = recv_until(pair.ws_guest, lambda e: e.get("type") == "user_left")
        assert event["payload"]["username"] == "ayush"
        ayush = participant_by_id(event["payload"]["participants"], pair.host["userId"])
        assert ayush["username"] == "ayush"
        assert ayush["online"] is False  # membership persists (10.3)

        # The leaver's own socket closes cleanly (drain past queued heartbeat pings).
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(pair.ws_host)
        assert exc.value.code == 1000


def test_refresh_keeps_role_and_rejoins(client, make_user_with_room) -> None:
    host = make_user_with_room()

    # First visit: the creator joins as host.
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        assert recv_until(ws, lambda e: e.get("type") == "room_joined")["payload"]["you"]["role"] == "host"

    # Refresh = plain disconnect (D-15 grace), not an intentional leave.
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        joined = recv_until(ws, lambda e: e.get("type") == "room_joined")
        assert joined["payload"]["you"]["role"] == "host"
        me = participant_by_id(joined["payload"]["participants"], host["userId"])
        assert me["online"] is True


def test_duplicate_names_get_a_suffix(client, make_user_with_room) -> None:
    host = make_user_with_room()
    guest = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], guest["userId"], guest["token"], "ayush"))
        joined = recv_until(ws, lambda e: e.get("type") == "room_joined")
        assert joined["payload"]["you"]["username"] == "ayush#2"


def test_empty_room_closes_after_ttl(client, make_user_with_room, monkeypatch) -> None:
    from watch_party.config import get_settings

    monkeypatch.setenv("EMPTY_ROOM_TTL_SECONDS", "0.3")
    get_settings.cache_clear()
    host = make_user_with_room()

    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")
        # Intentional leave: departure + empty-room scheduling run inside the
        # session. (A plain socket exit races TestClient teardown vs the
        # server finally block, so server-side departure is nondeterministic.)
        ws.send_json({"type": "leave_room", "payload": {"roomId": host["roomCode"]}})
        with pytest.raises(WebSocketDisconnect) as exc:
            drain_until_close(ws)
        assert exc.value.code == 1000

    # TTL elapsed with nobody online -> closed + forgotten (10.5).
    # Poll gently: the lookup limiter allows 30/min, so hammering trips 429s.
    def _closed() -> bool:
        body = client.get(f"/api/rooms/{host['roomCode']}").json()
        return body.get("joinable") is False

    wait_until(_closed, timeout=5.0, interval=0.2)

    check = client.get(f"/api/rooms/{host['roomCode']}").json()
    assert check["joinable"] is False
    assert check["reason"] == "not_found"

    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_text()
    assert exc.value.code == 4001


def test_join_within_ttl_cancels_cleanup(client, make_user_with_room, monkeypatch) -> None:
    from watch_party.config import get_settings

    monkeypatch.setenv("EMPTY_ROOM_TTL_SECONDS", "1.0")
    get_settings.cache_clear()
    host = make_user_with_room()
    guest = make_user_with_room()

    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")
    # Host left; the guest joins before the TTL expires.
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], guest["userId"], guest["token"], "neha"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")

        # Guest stays connected: the cleanup was cancelled by their join (10.5).
        # Wait past the original TTL, then the room must still be joinable.
        start = time.monotonic()
        wait_until(lambda: time.monotonic() > start + 1.3, timeout=5.0)
        check = client.get(f"/api/rooms/{host['roomCode']}").json()
        assert check["joinable"] is True
