"""Phase 7 integration tests: chat and reactions (architecture 8.2, 8.3, S-7, S-10).

One hard rule per test, driven through real WebSocket clients.
"""

from tests.conftest import error_of, receive_json_bounded, recv_until


def _next_responses(ws, count: int, timeout: float = 5.0) -> list[dict]:
    """Next `count` non-ping server events, answering pings on the way."""
    events: list[dict] = []
    while len(events) < count:
        event = receive_json_bounded(ws, timeout=timeout)
        if event.get("type") == "ping":
            ws.send_json({"type": "pong", "payload": {}})
            continue
        events.append(event)
    return events


def test_chat_broadcasts_to_everyone(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "chat", "payload": {"text": "hello all"}})
        for ws in (room.ws_host, room.ws_guest):
            message = recv_until(ws, lambda e: e.get("type") == "chat_message")["payload"]
            assert message["userId"] == room.guest["userId"]
            assert message["username"] == "neha"
            assert message["text"] == "hello all"
            assert message["createdAt"]


def test_chat_persists_for_late_joiner(client, joined_pair, make_user_with_room) -> None:
    from tests.conftest import TEST_ORIGIN, join_payload

    latecomer = make_user_with_room()
    with joined_pair as room:
        room.ws_guest.send_json({"type": "chat", "payload": {"text": "remember me"}})
        recv_until(room.ws_host, lambda e: e.get("type") == "chat_message")
        with client.websocket_connect(
            f"/ws/{room.code}", headers={"origin": TEST_ORIGIN}
        ) as ws_late:
            ws_late.send_json(
                join_payload(room.code, latecomer["userId"], latecomer["token"], "raj")
            )
            joined = recv_until(ws_late, lambda e: e.get("type") == "room_joined")["payload"]
            texts = [m["text"] for m in joined["recentChat"]]
            assert "remember me" in texts


def test_empty_chat_rejected_and_connection_survives(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "chat", "payload": {"text": "   "}})
        assert error_of(room.ws_guest)["code"] == "invalid_message"
        room.ws_guest.send_json({"type": "chat", "payload": {"text": "still here"}})
        message = recv_until(room.ws_host, lambda e: e.get("type") == "chat_message")["payload"]
        assert message["text"] == "still here"


def test_long_chat_rejected_and_connection_survives(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "chat", "payload": {"text": "x" * 501}})
        assert error_of(room.ws_guest)["code"] == "invalid_message"
        room.ws_guest.send_json({"type": "chat", "payload": {"text": "ok"}})
        message = recv_until(room.ws_host, lambda e: e.get("type") == "chat_message")["payload"]
        assert message["text"] == "ok"


def test_chat_sanitizes_control_characters(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "chat", "payload": {"text": "hi\x00there\x7f"}})
        message = recv_until(room.ws_host, lambda e: e.get("type") == "chat_message")["payload"]
        assert message["text"] == "hithere"


def test_chat_rate_limited(joined_pair) -> None:
    with joined_pair as room:
        for i in range(8):
            room.ws_guest.send_json({"type": "chat", "payload": {"text": f"msg {i}"}})
        events = _next_responses(room.ws_guest, 8)
        limited = [e for e in events if e.get("type") == "error"]
        assert len(limited) >= 2
        assert all(e["payload"]["code"] == "rate_limited" for e in limited)


def test_bad_emoji_rejected_and_connection_survives(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "reaction", "payload": {"emoji": "not-an-emoji"}})
        assert error_of(room.ws_guest)["code"] == "invalid_message"
        room.ws_guest.send_json({"type": "reaction", "payload": {"emoji": "👍"}})
        event = recv_until(room.ws_host, lambda e: e.get("type") == "reaction")["payload"]
        assert event["emoji"] == "👍"


def test_reaction_broadcasts_to_room(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "reaction", "payload": {"emoji": "🔥"}})
        event = recv_until(room.ws_host, lambda e: e.get("type") == "reaction")["payload"]
        assert event == {"userId": room.guest["userId"], "emoji": "🔥"}


def test_reaction_rate_limited(joined_pair) -> None:
    with joined_pair as room:
        for _ in range(8):
            room.ws_guest.send_json({"type": "reaction", "payload": {"emoji": "👍"}})
        events = _next_responses(room.ws_guest, 8)
        limited = [e for e in events if e.get("type") == "error"]
        assert len(limited) >= 1
        assert all(e["payload"]["code"] == "rate_limited" for e in limited)
