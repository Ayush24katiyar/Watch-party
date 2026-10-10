"""Room repository: creation, lookup, membership counts (architecture 8.1, 12)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from watch_party.config import get_settings
from watch_party.db.models import Room, RoomMember
from watch_party.domain.room_code import generate_room_code, normalize_code

# Live statuses: a closed room is reported as not_found (S-8).
_LIVE_STATUSES = ("open", "locked")


class RoomLimitExceeded(Exception):
    """A user may have at most a few live rooms at once (S-9)."""


async def create_room(session: AsyncSession, host_user_id: uuid.UUID) -> Room:
    """Create a room whose creator becomes host (5.2). Retries on code collision (8.1)."""
    if await count_live_rooms_for_user(session, host_user_id) >= get_settings().max_live_rooms_per_user:
        raise RoomLimitExceeded
    room = Room(code=generate_room_code(), host_user_id=host_user_id, status="open")
    # Codes are unique; regenerate on the rare collision (8.1).
    for _attempt in range(10):
        session.add(room)
        await session.flush()  # assigns room.id so the host member row can reference it
        session.add(
            RoomMember(
                room_id=room.id,
                user_id=host_user_id,
                username="host",
                role="host",
            )
        )
        try:
            await session.commit()
            return room
        except IntegrityError:
            await session.rollback()
            room.code = generate_room_code()
    raise RuntimeError("could not allocate a room code after 10 attempts")


async def get_room_by_code(session: AsyncSession, code: str) -> Room | None:
    """Codes are case-insensitive on input (8.1)."""
    normalized = normalize_code(code)
    result = await session.execute(
        select(Room).where(func.upper(Room.code) == normalized)
    )
    return result.scalar_one_or_none()


async def get_live_room_by_code(session: AsyncSession, code: str) -> Room | None:
    room = await get_room_by_code(session, code)
    if room is None or room.status not in _LIVE_STATUSES:
        return None
    return room


async def count_members(session: AsyncSession, room_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(RoomMember).where(RoomMember.room_id == room_id)
    )
    return int(result.scalar_one())


async def count_live_rooms_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Room)
        .where(Room.host_user_id == user_id, Room.status.in_(_LIVE_STATUSES))
    )
    return int(result.scalar_one())


async def set_room_status(session: AsyncSession, room_id: uuid.UUID, status: str) -> None:
    """open | locked (Phase 4 lock_room) | closed (10.5 cleanup)."""
    room = await session.get(Room, room_id)
    if room is None:
        return
    room.status = status
    await session.commit()


async def save_state_snapshot(
    session: AsyncSession,
    room_id: uuid.UUID,
    video_id: str | None,
    play_state: str,
    position: float,
    seq: int,
) -> None:
    """Debounced persistence of the playback snapshot (D-22; wired in Phase 5)."""
    room = await session.get(Room, room_id)
    if room is None:
        return
    room.video_id = video_id
    room.play_state = play_state
    room.position = position
    room.seq = seq
    await session.commit()
