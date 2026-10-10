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


class JoinRoomMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["join_room"]
    payload: JoinRoomPayload


class PongMessage(BaseModel):
    model_config = _WIRE_CONFIG

    type: Literal["pong"]
    payload: dict[str, Any]


# Discriminated union: the "type" field selects the schema (S-5).
ClientMessage = Annotated[
    JoinRoomMessage | PongMessage,
    Field(discriminator="type"),
]

client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)
