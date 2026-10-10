"""MessageRouter: parse the envelope, validate it, dispatch to the Connection.

Invalid or unknown input becomes an `error` message; the connection stays open
unless the connection's abuse limits close it (S-5, 10.2).
"""

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from watch_party.ws.schemas import client_message_adapter

if TYPE_CHECKING:
    from watch_party.ws.endpoint import Connection


class MessageRouter:
    def __init__(self, connection: "Connection") -> None:
        self._connection = connection
        self._handlers = {
            "join_room": connection.on_join_room,
            "pong": connection.on_pong,
        }

    async def route(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await self._connection.reject("invalid_message", "Message is not valid JSON.")
            return

        if not isinstance(data, dict):
            await self._connection.reject("invalid_message", "Message must be a JSON object.")
            return

        request_id = data.get("requestId")

        try:
            message = client_message_adapter.validate_python(data)
        except ValidationError:
            await self._connection.reject(
                "invalid_message",
                "Unknown message type or invalid payload.",
                request_id,
            )
            return

        handler = self._handlers.get(message.type)
        if handler is None:
            await self._connection.reject(
                "invalid_message",
                f"Unsupported message type: {message.type}",
                request_id,
            )
            return

        payload: dict[str, Any] = message.payload  # type: ignore[assignment]
        await handler(payload, request_id)
