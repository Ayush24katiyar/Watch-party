"""Playback unit tests: effective_position and transitions (architecture 11, D-7)."""

from unittest.mock import patch

import pytest
from pydantic import TypeAdapter, ValidationError

from watch_party.domain.room import Room
from watch_party.ws.schemas import ChangeVideoPayload


def make_room() -> Room:
    room = Room("ABC123", "host-1")
    room.add(type("P", (), {"user_id": "host-1", "online": True, "connection": object()})())
    return room


def test_effective_position_advances_while_playing() -> None:
    room = make_room()
    with patch("watch_party.domain.room.time.monotonic", return_value=1000.0):
        room.video_state.update(
            {"video_id": "abcdefghijk", "play_state": "playing", "position": 10.0, "updated_at": 999.5}
        )
        assert room.effective_position() == 10.5


def test_effective_position_frozen_while_paused() -> None:
    room = make_room()
    with patch("watch_party.domain.room.time.monotonic", return_value=1000.0):
        room.video_state.update(
            {"video_id": "abcdefghijk", "play_state": "paused", "position": 7.5, "updated_at": 900.0}
        )

        assert room.effective_position() == 7.5


def test_play_bumps_seq_and_stamps_position() -> None:
    room = make_room()
    state = room.apply_play(None)

    assert state["playState"] == "playing"
    assert state["seq"] == 1
    assert state["videoId"] is None


def test_play_accepts_client_time() -> None:
    room = make_room()
    state = room.apply_play(42.0)

    assert state["currentTime"] == 42.0


def test_seek_sets_position_and_keeps_play_state() -> None:
    room = make_room()
    room.apply_play(None)
    state = room.apply_seek(5.0)

    assert state["playState"] == "playing"
    assert state["currentTime"] == 5.0
    assert state["seq"] == 2


def test_change_video_resets_to_paused_at_zero() -> None:
    room = make_room()
    room.apply_play(100.0)
    state = room.apply_change_video("dQw4w9WgXcQ")

    assert state["videoId"] == "dQw4w9WgXcQ"
    assert state["playState"] == "paused"
    assert state["currentTime"] == 0.0
    assert state["seq"] == 2


@pytest.mark.parametrize(
    "video_id",
    ["dQw4w9WgXcQ", "a-b_C9Z2v12", "AAAAAAAAAAA"],
)
def test_valid_video_ids(video_id: str) -> None:
    adapter: TypeAdapter[ChangeVideoPayload] = TypeAdapter(ChangeVideoPayload)
    assert adapter.validate_python({"videoId": video_id}).video_id == video_id


@pytest.mark.parametrize(
    "video_id",
    ["", "too_short", "has spaces!", "dQw4w9WgXcQQ"],  # last one is 12 chars
)
def test_invalid_video_ids(video_id: str) -> None:
    adapter: TypeAdapter[ChangeVideoPayload] = TypeAdapter(ChangeVideoPayload)
    with pytest.raises(ValidationError):
        adapter.validate_python({"videoId": video_id})


@pytest.mark.parametrize("time_value", [-1, 86401])
def test_seek_time_out_of_bounds(time_value: float) -> None:
    from watch_party.ws.schemas import SeekPayload

    with pytest.raises(ValidationError):
        TypeAdapter(SeekPayload).validate_python({"time": time_value})
