"""MessageRouter: parse the envelope, validate it, dispatch to handlers.

Permission is checked BEFORE dispatch (section 9): the backend, not the UI,
decides who may do what. Invalid or unknown input becomes an `error` message;
the connection stays open unless the connection's abuse limits close it (S-5, 10.2).
"""

import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from watch_party.domain import permissions
from watch_party.logging import get_logger, log_event
from watch_party.ws.handlers import chat as chat_handlers
from watch_party.ws.handlers import playback as playback_handlers
from watch_party.ws.handlers import requests as request_handlers
from watch_party.ws.handlers import roles as role_handlers
from watch_party.ws.schemas import client_message_adapter

if TYPE_CHECKING:
    from watch_party.ws.endpoint import Connection

# (connection, payload, requestId) -> None
Handler = Callable[["Connection", dict[str, Any], "str | None"], Awaitable[None]]


class MessageRouter:
    def __init__(self, connection: "Connection") -> None:
        self._connection = connection
        self._handlers: dict[str, Handler] = {
            "join_room": lambda conn, payload, request_id: conn.on_join_room(
                payload, request_id
            ),
            "pong": lambda conn, payload, request_id: conn.on_pong(payload, request_id),
            "leave_room": lambda conn, payload, request_id: conn.on_leave_room(
                payload, request_id
            ),
            "assign_role": role_handlers.handle_assign_role,
            "remove_participant": role_handlers.handle_remove_participant,
            "transfer_host": role_handlers.handle_transfer_host,
            "lock_room": role_handlers.handle_lock_room,
            "play": playback_handlers.handle_play,
            "pause": playback_handlers.handle_pause,
            "seek": playback_handlers.handle_seek,
            "change_video": playback_handlers.handle_change_video,
            "request_action": request_handlers.handle_request_action,
            "resolve_request": request_handlers.handle_resolve_request,
            "chat": chat_handlers.handle_chat,
            "reaction": chat_handlers.handle_reaction,
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

        action = permissions.ACTION_BY_TYPE.get(message.type)
        if action is not None:
            you = self._connection.you
            if you is None or not permissions.can(you.role, action):
                await self._connection.reject(
                    "forbidden",
                    "Your role cannot perform this action.",
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

        # Handlers read camelCase dicts, mirroring the wire format (D-18).
        # Some payloads are typed models, some plain dicts (play/pause).
        payload: dict[str, Any] = (
            message.payload.model_dump(by_alias=True)
            if hasattr(message.payload, "model_dump")
            else dict(message.payload)
        )
        you = self._connection.you
        log_event(
            message.type,
            user_id=str(you.user_id) if you is not None else None,
            room_code=self._connection.room.code if self._connection.room else None,
        )
        # A handler bug must not take the connection (and its heartbeat task)
        # down with it: report and keep the socket alive (B-021).
        try:
            await handler(self._connection, payload, request_id)
        except Exception:  # noqa: BLE001 - deliberate catch-all guard
            get_logger().exception(
                "handler failed type=%s room=%s user=%s",
                message.type,
                self._connection.room.code if self._connection.room else None,
                str(you.user_id) if you is not None else None,
            )
            await self._connection.reject(
                "internal_error",
                "That action could not be completed.",
                request_id,
            )
