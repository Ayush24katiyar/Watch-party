"""Playback handlers: play, pause, seek, change_video (Phase 5, section 11).

Every action updates the server-authoritative state (D-7), broadcasts
`sync_state` to the room, and schedules a debounced DB snapshot (D-22).
Permission is enforced by the MessageRouter before these run (section 9).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from watch_party.ws.endpoint import Connection


async def _apply(connection: "Connection", transition, request_id: str | None) -> None:
    room = connection.room
    if room is None:
        await connection.reject("not_found", "Not in a room.")
        return
    try:
        state = transition()
    except (KeyError, TypeError, ValueError):
        await connection.reject("invalid_message", "Invalid playback payload.", request_id)
        return
    await room.broadcast({"type": "sync_state", "payload": state})
    connection.schedule_snapshot(room)


async def handle_play(connection: "Connection", payload: dict[str, Any], request_id: str | None) -> None:
    room = connection.room
    await _apply(connection, lambda: room.apply_play(payload.get("time")), request_id)


async def handle_pause(connection: "Connection", payload: dict[str, Any], request_id: str | None) -> None:
    room = connection.room
    await _apply(connection, lambda: room.apply_pause(payload.get("time")), request_id)


async def handle_seek(connection: "Connection", payload: dict[str, Any], request_id: str | None) -> None:
    room = connection.room
    await _apply(connection, lambda: room.apply_seek(payload["time"]), request_id)


async def handle_change_video(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room = connection.room
    await _apply(connection, lambda: room.apply_change_video(payload["videoId"]), request_id)
