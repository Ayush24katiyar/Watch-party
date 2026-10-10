"""Room membership repository (architecture section 10.1)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watch_party.db.models import RoomMember
from watch_party.domain.roles import Role


async def get_members(session: AsyncSession, room_id: uuid.UUID) -> list[RoomMember]:
    result = await session.execute(
        select(RoomMember)
        .where(RoomMember.room_id == room_id)
        .order_by(RoomMember.joined_at)
    )
    return list(result.scalars().all())


async def get_member(
    session: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID
) -> RoomMember | None:
    result = await session.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def add_member(
    session: AsyncSession,
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    username: str,
    role: Role = Role.PARTICIPANT,
) -> RoomMember:
    """New joiners are participants; the room creator already has a host row (5.2)."""
    member = RoomMember(
        room_id=room_id,
        user_id=user_id,
        username=username,
        role=role.value,
    )
    session.add(member)
    await session.commit()
    return member


async def update_username(
    session: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID, username: str
) -> None:
    """Replace the creator placeholder with the chosen name (10.1)."""
    member = await get_member(session, room_id, user_id)
    if member is None:
        return
    member.username = username
    await session.commit()


async def ban_member(session: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Removed users cannot rejoin this room (D-16; remove flow lands in Phase 4)."""
    member = await get_member(session, room_id, user_id)
    if member is None:
        return
    member.is_banned = True
    await session.commit()
