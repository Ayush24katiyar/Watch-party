"""Approval request handlers (Phase 6, sections 8.2, 8.3, R-7).

A Participant asks for a playback change; a Host/Moderator approves or
rejects. Approval re-checks that the request is still pending, not expired and
the requester is still present (R-7), then runs the *real* playback handler.
"""

import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from watch_party.ws.schemas import ChangeVideoPayload, SeekPayload

if TYPE_CHECKING:
    from watch_party.ws.endpoint import Connection

_PLAYBACK_ACTIONS = ("play", "pause", "seek", "change_video")


class _PlayPausePayload(BaseModel):
    """play/pause take any payload (8.2); only `time` is typed, and optional (D-20)."""

    model_config = ConfigDict(extra="ignore")

    time: float | None = Field(default=None, ge=0, le=86400)


# The inner payload of a request must satisfy the same schema the real message
# does (8.2). Without this, a request stored with `payload: {}` crashes the
# approver with a KeyError at approval time (B-021).
_INNER_PAYLOAD_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "play": TypeAdapter(_PlayPausePayload),
    "pause": TypeAdapter(_PlayPausePayload),
    "seek": TypeAdapter(SeekPayload),
    "change_video": TypeAdapter(ChangeVideoPayload),
}


async def handle_request_action(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room, you = connection.room, connection.you
    if room is None or you is None:
        await connection.reject("not_found", "Not in a room.")
        return

    action = payload.get("action")
    if action not in _PLAYBACK_ACTIONS:
        await connection.reject("invalid_message", "Unsupported request action.")
        return

    # Validate now so approval can never hit a missing or ill-typed key later.
    try:
        inner = _INNER_PAYLOAD_ADAPTERS[action].validate_python(payload.get("payload") or {})
    except ValidationError:
        await connection.reject("invalid_message", "Invalid payload for the requested action.")
        return

    request = room.create_request(
        you,
        action,
        inner.model_dump(by_alias=True, exclude_none=True),
        connection.settings.request_ttl_seconds,
    )
    if request is None:
        await connection.reject("conflict", "Too many pending requests.")
        return

    # 8.3: host + moderators (and the requester) hear about the request.
    controllers = {
        p.user_id for p in room if p.online and p.role.value in ("host", "moderator")
    }
    controllers.add(you.user_id)
    await room.broadcast_to(
        {
            "type": "request_created",
            "payload": {
                "requestId": request["requestId"],
                "userId": you.user_id,
                "username": you.username,
                "action": action,
                "payload": request["payload"],
                "expiresAt": request["expiresAt"],
            },
        },
        include=controllers,
    )


async def handle_resolve_request(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room, you = connection.room, connection.you
    if room is None or you is None:
        await connection.reject("not_found", "Not in a room.")
        return

    pending = room.get_request(payload.get("requestId", ""))
    approve = bool(payload.get("approve"))

    # R-7: re-check everything before applying.
    if pending is None or pending["expiresAt"] <= time.time():
        await connection.reject("request_expired", "Request is no longer pending.")
        return
    requester = room.participants.get(pending["user_id"])
    if requester is None:
        await connection.reject("request_expired", "Requester is no longer present.")
        return

    room.remove_request(pending["requestId"])
    action = pending["action"]
    request_payload = pending["payload"]

    if approve:
        # Re-validate before applying: requests stored before inner-payload
        # validation existed must not crash the approver (B-021).
        try:
            inner = _INNER_PAYLOAD_ADAPTERS[action].validate_python(request_payload)
        except ValidationError:
            await connection.reject("invalid_message", "Request payload is no longer valid.")
            return
        # Run the same handler a Moderator would use (R-7).
        state = None
        if action == "play":
            state = room.apply_play(inner.time)
        elif action == "pause":
            state = room.apply_pause(inner.time)
        elif action == "seek":
            state = room.apply_seek(inner.time)
        elif action == "change_video":
            state = room.apply_change_video(inner.video_id)
        await room.broadcast({"type": "sync_state", "payload": state})
        connection.schedule_snapshot(room)

    await room.broadcast(
        {
            "type": "request_resolved",
            "payload": {
                "requestId": pending["requestId"],
                "approved": approve,
                "participants": room.participant_snapshots(),
            },
        }
    )