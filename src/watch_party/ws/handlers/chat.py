"""Chat and reaction handlers (Phase 7, sections 8.2, 8.3, S-7, S-10).

Chat persists to the database and is replayed in room_joined (last 50).
Reactions are ephemeral. Both are rate-limited per connection.
"""

import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from watch_party.db.engine import SessionLocal
from watch_party.repositories import chat as chat_repo

if TYPE_CHECKING:
    from watch_party.ws.endpoint import Connection

# Fixed allow-list (16): no free-form emoji input.
ALLOWED_EMOJI = frozenset(["👍", "❤️", "😂", "😮", "😢", "👏", "🎉", "🔥"])

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_chat_text(raw: str) -> str:
    """S-10: strip control characters, trim, cap at 500."""
    return _CONTROL_CHARS.sub("", raw).strip()[:500]


async def handle_chat(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room, you = connection.room, connection.you
    if room is None or you is None:
        await connection.reject("not_found", "Not in a room.")
        return
    text = sanitize_chat_text(payload.get("text", ""))
    if not text:
        await connection.reject("invalid_message", "Chat text must not be empty.")
        return
    if not connection.chat_bucket.consume():
        await connection.reject("rate_limited", "Slow down; too many chat messages.")
        return

    async with SessionLocal() as session:
        message = await chat_repo.add_message(session, room.db_id, UUID(you.user_id), text)

    await room.broadcast(
        {
            "type": "chat_message",
            "payload": {
                "userId": you.user_id,
                "username": you.username,
                "text": text,
                "createdAt": message.created_at.isoformat(),
            },
        }
    )


async def handle_reaction(
    connection: "Connection", payload: dict[str, Any], request_id: str | None
) -> None:
    room, you = connection.room, connection.you
    if room is None or you is None:
        await connection.reject("not_found", "Not in a room.")
        return
    emoji = payload.get("emoji")
    if emoji not in ALLOWED_EMOJI:
        await connection.reject("invalid_message", "Emoji is not in the allow-list.")
        return
    if not connection.reaction_bucket.consume():
        await connection.reject("rate_limited", "Slow down; too many reactions.")
        return

    await room.broadcast(
        {"type": "reaction", "payload": {"userId": you.user_id, "emoji": emoji}}
    )
