"""Phase 5 integration tests: playback sync (architecture 16, 11)."""

from tests.conftest import TEST_ORIGIN, error_of, join_payload, recv_until


def test_host_play_broadcasts_identical_sync_state(joined_pair) -> None:
    with joined_pair as room:
        room.ws_host.send_json({"type": "play", "payload": {}})

        host_state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        guest_state = recv_until(room.ws_guest, lambda e: e.get("type") == "sync_state")["payload"]

    assert host_state == guest_state
    assert host_state["playState"] == "playing"
    assert host_state["seq"] == 1


def test_seek_updates_everyone(joined_pair) -> None:
    with joined_pair as room:
        room.ws_host.send_json({"type": "seek", "payload": {"time": 30}})

        state = recv_until(room.ws_guest, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["currentTime"] == 30
        assert state["seq"] == 1


def test_participant_change_video_is_forbidden_and_silent(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "change_video", "payload": {"videoId": "dQw4w9WgXcQ"}})

        error = recv_until(room.ws_guest, lambda e: e.get("type") == "error")["payload"]
        assert error["code"] == "forbidden"
        # The host hears nothing: no state change, no broadcast.
        room.ws_host.send_json({"type": "play", "payload": {}})
        state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["seq"] == 1  # only the host's own play happened


def test_participant_play_is_forbidden(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "play", "payload": {}})
        assert recv_until(room.ws_guest, lambda e: e.get("type") == "error")["payload"]["code"] == "forbidden"


def test_participant_seek_is_forbidden_and_silent(joined_pair) -> None:
    with joined_pair as room:
        room.ws_guest.send_json({"type": "seek", "payload": {"time": 30}})
        assert error_of(room.ws_guest)["code"] == "forbidden"
        # No state change happened: the host's own play is still seq 1.
        room.ws_host.send_json({"type": "play", "payload": {}})
        state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["seq"] == 1


def test_change_video_resets_playback(client, make_user_with_room) -> None:
    host = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")
        ws.send_json({"type": "change_video", "payload": {"videoId": "dQw4w9WgXcQ"}})
        state = recv_until(ws, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["videoId"] == "dQw4w9WgXcQ"
        assert state["playState"] == "paused"
        assert state["currentTime"] == 0


def test_invalid_video_id_is_rejected(client, make_user_with_room) -> None:
    host = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")
        ws.send_json({"type": "change_video", "payload": {"videoId": "not-valid"}})
        assert recv_until(ws, lambda e: e.get("type") == "error")["payload"]["code"] == "invalid_message"


def test_out_of_bounds_seek_is_rejected(client, make_user_with_room) -> None:
    host = make_user_with_room()
    with client.websocket_connect(f"/ws/{host['roomCode']}", headers={"origin": TEST_ORIGIN}) as ws:
        ws.send_json(join_payload(host["roomCode"], host["userId"], host["token"], "ayush"))
        recv_until(ws, lambda e: e.get("type") == "room_joined")
        ws.send_json({"type": "seek", "payload": {"time": 99999}})
        assert recv_until(ws, lambda e: e.get("type") == "error")["payload"]["code"] == "invalid_message"


def test_seek_string_time_rejected_and_open(joined_pair) -> None:
    with joined_pair as room:
        room.ws_host.send_json({"type": "seek", "payload": {"time": "soon"}})
        assert error_of(room.ws_host)["code"] == "invalid_message"
        room.ws_host.send_json({"type": "play", "payload": {}})
        state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["seq"] == 1


def test_seek_missing_time_rejected_and_open(joined_pair) -> None:
    with joined_pair as room:
        room.ws_host.send_json({"type": "seek", "payload": {}})
        assert error_of(room.ws_host)["code"] == "invalid_message"
        room.ws_host.send_json({"type": "play", "payload": {}})
        state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["seq"] == 1


def test_play_string_time_rejected_and_open(joined_pair) -> None:
    with joined_pair as room:
        room.ws_host.send_json({"type": "play", "payload": {"time": "abc"}})
        assert error_of(room.ws_host)["code"] == "invalid_message"
        room.ws_host.send_json({"type": "play", "payload": {}})
        state = recv_until(room.ws_host, lambda e: e.get("type") == "sync_state")["payload"]
        assert state["playState"] == "playing"
        assert state["seq"] == 1


def test_seek_negative_rejected(joined_pair) -> None:
    with joined_pair as room:
        room.ws_host.send_json({"type": "seek", "payload": {"time": -5}})
        assert error_of(room.ws_host)["code"] == "invalid_message"


def test_pause_then_play_sequence(joined_pair) -> None:
    with joined_pair as room:
        room.ws_host.send_json({"type": "pause", "payload": {}})
        paused = recv_until(room.ws_guest, lambda e: e.get("type") == "sync_state")["payload"]
        assert paused["playState"] == "paused"
        assert paused["seq"] == 1
        room.ws_host.send_json({"type": "play", "payload": {}})
        playing = recv_until(room.ws_guest, lambda e: e.get("type") == "sync_state")["payload"]
        assert playing["playState"] == "playing"
        assert playing["seq"] == 2


def test_change_video_then_play_sequence(joined_pair) -> None:
    with joined_pair as room:
        room.ws_host.send_json({"type": "change_video", "payload": {"videoId": "dQw4w9WgXcQ"}})
        changed = recv_until(room.ws_guest, lambda e: e.get("type") == "sync_state")["payload"]
        assert changed["videoId"] == "dQw4w9WgXcQ"
        assert changed["playState"] == "paused"
        assert changed["currentTime"] == 0
        assert changed["seq"] == 1
        room.ws_host.send_json({"type": "play", "payload": {}})
        playing = recv_until(room.ws_guest, lambda e: e.get("type") == "sync_state")["payload"]
        assert playing["videoId"] == "dQw4w9WgXcQ"
        assert playing["playState"] == "playing"
        assert playing["seq"] == 2
