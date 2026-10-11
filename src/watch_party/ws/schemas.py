"""Pydantic schemas for the WebSocket wire protocol (Phase 1 subset).

Envelope: {"type": "...", "payload": {...}, "requestId"?: str}
Wire format is camelCase (D-18); unknown fields are rejected (S-5).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# camelCase aliases + populate_by_name so Python code can use snake_case.
_WIRE_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)


class JoinRoomPayload(BaseModel):
    """join_room payload (8.2). Auth/room lookup are Phase 2; Phase 1 only validates."""

    model_config = _WIRE_CONFIG

    room_id: str = Field(alias="roomId")
    username: str
    user_id: str = Field(alias="userId")
    token: str


class _UserIdPayload(BaseModel):
    """Shared `{userId}` payload for host actions (8.2)."""

    model_config = _WIRE_CONFIG

    user_id: str = Field(alias="userId")


class _LockedPayload(BaseModel):
    """Shared `{locked}` payload for lock_room (8.2)."""

    model_config = _WIRE_CONFIG

    locked: bool


class JoinRoomMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["join_room"]
    payload: JoinRoomPayload


class PongMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["pong"]
    payload: dict[str, Any]


class LeaveRoomPayload(BaseModel):
    model_config = _WIRE_CONFIG

    room_id: str = Field(alias="roomId")


class LeaveRoomMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["leave_room"]
    payload: LeaveRoomPayload


class AssignRolePayload(BaseModel):
    model_config = _WIRE_CONFIG

    user_id: str = Field(alias="userId")
    # host is not assignable through assign_role (D-17).
    role: Literal["moderator", "participant"]


class AssignRoleMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["assign_role"]
    payload: AssignRolePayload


class RemoveParticipantMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["remove_participant"]
    payload: _UserIdPayload


class TransferHostMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["transfer_host"]
    payload: _UserIdPayload


class LockRoomMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["lock_room"]
    payload: _LockedPayload


# --- playback (Phase 5, section 8.2) ---

_VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{11}$"


class PlayMessage(BaseModel):
    """`time` is optional (D-20): the controller may report the exact position."""

    model_config = _WIRE_CONFIG

    type: Literal["play"]
    payload: dict[str, Any] = Field(default_factory=dict)


class PauseMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["pause"]
    payload: dict[str, Any] = Field(default_factory=dict)


class SeekPayload(BaseModel):
    model_config = _WIRE_CONFIG

    time: float = Field(ge=0, le=86400)


class SeekMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["seek"]
    payload: SeekPayload


class ChangeVideoPayload(BaseModel):
    model_config = _WIRE_CONFIG

    video_id: str = Field(pattern=_VIDEO_ID_PATTERN, alias="videoId")


class ChangeVideoMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["change_video"]
    payload: ChangeVideoPayload


# --- approval requests (Phase 6, section 8.2) ---

class RequestActionPayload(BaseModel):
    model_config = _WIRE_CONFIG

    action: Literal["play", "pause", "seek", "change_video"]
    payload: dict[str, Any] = Field(default_factory=dict)


class RequestActionMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["request_action"]
    payload: RequestActionPayload


class ResolveRequestPayload(BaseModel):
    model_config = _WIRE_CONFIG

    request_id: str = Field(alias="requestId")
    approve: bool


class ResolveRequestMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["resolve_request"]
    payload: ResolveRequestPayload


# --- chat and reactions (Phase 7, section 8.2) ---

class ChatMessagePayload(BaseModel):
    model_config = _WIRE_CONFIG

    text: str = Field(min_length=1, max_length=500)


class ChatMessageWire(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["chat"]
    payload: ChatMessagePayload


class ReactionMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["reaction"]
    payload: "ReactionPayload"


class ReactionPayload(BaseModel):
    model_config = _WIRE_CONFIG

    emoji: str


# Discriminated union: the "type" field selects the schema (S-5).
ClientMessage = Annotated[
    (
        JoinRoomMessage
        | PongMessage
        | LeaveRoomMessage
        | AssignRoleMessage
        | RemoveParticipantMessage
        | TransferHostMessage
        | LockRoomMessage
        | PlayMessage
        | PauseMessage
        | SeekMessage
        | ChangeVideoMessage
        | RequestActionMessage
        | ResolveRequestMessage
        | ChatMessageWire
        | ReactionMessage
    ),
    Field(discriminator="type"),
]

client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)
