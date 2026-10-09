"""Phase 1 integration tests: WebSocket foundation (architecture 16, 18).

Settings are overridden per test so the 5 s join timeout and 20/40 s heartbeat
stay fast.
"""

import json

import pytest
from starlette.websockets import WebSocketDisconnect

ORIGIN = "http://localhost:5173"
WS_PATH = "/ws/dev"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JOIN_TIMEOUT_SECONDS", "0.3")
    monkeypatch.setenv("WS_PING_INTERVAL_SECONDS", "0.2")
    monkeypatch.setenv("WS_PING_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("WS_RATE_LIMIT_OTHER_PER_SECOND", "5")
    monkeypatch.setenv("WS_MAX_SIZE_BYTES", "200")
    monkeypatch.setenv("WS_ABUSE_WINDOW_SECONDS", "60")
    monkeypatch.setenv("WS_MAX_INVALID_PER_WINDOW", "10")
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setenv("ALLOW_MISSING_ORIGIN", "false")

    from fastapi.testclient import TestClient

    from watch_party.config import get_settings
    from watch_party.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def join() -> str:
    return json.dumps(
        {
            "type": "join_room",
            "payload": {"roomId": "dev", "username": "dev", "userId": "dev", "token": "dev"},
        }
    )


def error_code(message: dict) -> str:
    assert message["type"] == "error"
    return message["payload"]["code"]


# --- Phase 1 done-when cases (architecture 16) ---


def test_silent_socket_closes_with_4007(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            # Drain heartbeats until the join-timeout close arrives.
            while True:
                ws.receive_text()
    assert exc.value.code == 4007


def test_malformed_json_returns_error_and_stays_open(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_text("{not json")
        assert error_code(ws.receive_json()) == "invalid_message"
        # Still usable: join and echo work after the error.
        ws.send_text(join())
        ws.send_json({"type": "echo", "payload": {"hello": "world"}})
        assert ws.receive_json()["payload"] == {"hello": "world"}


def test_unknown_type_returns_error(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_text(join())
        ws.send_json({"type": "play", "payload": {}})
        assert error_code(ws.receive_json()) == "invalid_message"


def test_extra_field_is_rejected(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_text(join())
        ws.send_json({"type": "echo", "payload": {}, "extra": 1})
        assert error_code(ws.receive_json()) == "invalid_message"


def test_bad_origin_is_rejected(client) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(WS_PATH, headers={"origin": "http://evil.com"}) as ws:
            ws.receive_text()


def test_missing_origin_rejected_by_default(client) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(WS_PATH) as ws:
            ws.receive_text()


def test_missing_origin_allowed_when_setting_true(client, monkeypatch) -> None:
    from watch_party.config import get_settings

    monkeypatch.setenv("ALLOW_MISSING_ORIGIN", "true")
    get_settings.cache_clear()
    try:
        with client.websocket_connect(WS_PATH) as ws:  # no Origin header at all
            ws.send_text(join())
            ws.send_json({"type": "echo", "payload": {"debugger": True}})
            assert ws.receive_json()["payload"] == {"debugger": True}
    finally:
        get_settings.cache_clear()


def test_oversized_message_closes_with_4007(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_text(join())
        ws.send_text(json.dumps({"type": "echo", "payload": {"blob": "x" * 500}}))
        assert error_code(ws.receive_json()) == "invalid_message"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    assert exc.value.code == 4007


def test_first_message_must_be_join_room(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_json({"type": "pong", "payload": {}})
        assert error_code(ws.receive_json()) == "invalid_message"
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_text()
    assert exc.value.code == 4007


def test_invalid_join_payload_then_close_4007(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_json({"type": "join_room", "payload": {}})
        assert error_code(ws.receive_json()) == "invalid_message"
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_text()
    assert exc.value.code == 4007


def test_rate_limited_burst_gets_error(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_text(join())
        # Bucket is 5/s; join + 9 pongs = 10 messages -> some must be rate_limited.
        for _ in range(9):
            ws.send_json({"type": "pong", "payload": {}})
        codes = [error_code(ws.receive_json()) for _ in range(5)]
        assert "rate_limited" in codes


def test_ping_pong_keeps_connection_alive(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_text(join())
        # Server pings every 0.2s; the test client replies pong like the real client does.
        first = ws.receive_json()
        assert first["type"] == "ping"
        ws.send_json({"type": "pong", "payload": {}})
        for _ in range(3):
            assert ws.receive_json()["type"] == "ping"
            ws.send_json({"type": "pong", "payload": {}})
        ws.send_json({"type": "echo", "payload": {"still": "alive"}})
        assert ws.receive_json()["payload"] == {"still": "alive"}


def test_zombie_connection_closes_with_1001(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_text(join())
        # No pongs: heartbeat timeout (0.5s) must close the socket with 1001.
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                message = ws.receive_json()
                if message.get("type") == "ping":
                    continue  # deliberately never pong
    assert exc.value.code == 1001


def test_error_includes_request_id(client) -> None:
    with client.websocket_connect(WS_PATH, headers={"origin": ORIGIN}) as ws:
        ws.send_text(join())
        ws.send_json({"type": "play", "payload": {}, "requestId": "req-1"})
        message = ws.receive_json()
        assert message["payload"]["requestId"] == "req-1"
