"""Chat repository (Phase 7, section 12)."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watch_party.db.models import ChatMessage, RoomMember

RECENT_CHAT_LIMIT = 50


async def add_message(
    session: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID, text: str
) -> ChatMessage:
    message = ChatMessage(room_id=room_id, user_id=user_id, text=text)
    session.add(message)
    await session.commit()
    return message


async def recent_messages(session: AsyncSession, room_id: uuid.UUID) -> list[dict[str, Any]]:
    """Last 50 messages with usernames, oldest first (for room_joined)."""
    result = await session.execute(
        select(ChatMessage, RoomMember.username)
        .join(
            RoomMember,
            (ChatMessage.room_id == RoomMember.room_id)
            & (ChatMessage.user_id == RoomMember.user_id),
        )
        .where(ChatMessage.room_id == room_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(RECENT_CHAT_LIMIT)
    )
    rows = list(reversed(result.all()))
    return [
        {
            "userId": str(message.user_id),
            "username": username,
            "text": message.text,
            "createdAt": message.created_at.isoformat(),
        }
        for message, username in rows
    ]
