"""Diagnostics endpoints (local development only).

These exist so a browser problem can be pinned down from the terminal: what the
server believes about a room, which sockets are live, and the last N events.
Never mounted in production (config.debug_endpoints).
"""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from watch_party.db.engine import SessionLocal
from watch_party.db.models import ChatMessage, Room, RoomMember
from watch_party.debug.recorder import clear, recent, record
from watch_party.domain.room_manager import room_manager
from watch_party.repositories import rooms as room_repo

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/state")
async def state() -> dict[str, Any]:
    """One-shot picture: live rooms, sockets, and what the database thinks."""
    connections = room_manager.all_connections()
    async with SessionLocal() as session:
        db_rooms = (
            await session.execute(select(Room.code, Room.status, Room.video_id, Room.seq))
        ).all()
        live_for_user = (
            await session.execute(
                select(Room.host_user_id).where(Room.status.in_(("open", "locked")))
            )
        ).scalars().all()
    from collections import Counter

    return {
        "memory": {
            "rooms": [room.code for room in room_manager.all_rooms()],
            "room_count": len(room_manager.all_rooms()),
            "connections": len(connections),
        },
        "database": {
            "rooms": len(db_rooms),
            "live_rooms": len(live_for_user),
            "status_counts": dict(Counter(status for _, status, _, _ in db_rooms)),
        },
        "sockets": [
            {
                "room": connection.room.code if connection.room else None,
                "user": connection.you.username if connection.you else None,
                "user_id": connection.you.user_id if connection.you else None,
                "joined": connection._joined,
            }
            for connection in connections
        ],
    }


@router.get("/rooms/{code}")
async def room_detail(code: str) -> dict[str, Any]:
    """Everything known about one room, from memory and from the database."""
    room = room_manager.get(code)
    live: dict[str, Any] | None = None
    if room is not None:
        live = {
            "code": room.code,
            "host_user_id": room.host_user_id,
            "locked": room.locked,
            "db_id": str(room.db_id) if room.db_id else None,
            "playback": room.state_snapshot(),
            "participants": [
                {
                    "username": p.username,
                    "user_id": p.user_id,
                    "role": p.role.value,
                    "online": p.online,
                }
                for p in room
            ],
            "pending_requests": [
                {"username": r["username"], "action": r["action"]}
                for r in room.pending_requests.values()
            ],
        }

    db: dict[str, Any] | None = None
    async with SessionLocal() as session:
        row = await session.execute(
            select(Room).where(Room.code == code.strip().upper())
        )
        found = row.scalar_one_or_none()
        if found is not None:
            members = (
                await session.execute(
                    select(RoomMember).where(RoomMember.room_id == found.id)
                )
            ).scalars().all()
            chat_count = (
                await session.execute(
                    select(ChatMessage).where(ChatMessage.room_id == found.id)
                )
            ).scalars().all()
            db = {
                "status": found.status,
                "video_id": found.video_id,
                "play_state": found.play_state,
                "position": round(found.position, 2),
                "seq": found.seq,
                "updated_at": found.updated_at.isoformat(),
                "members": [
                    {"username": m.username, "role": m.role, "banned": m.is_banned}
                    for m in members
                ],
                "chat_messages": len(chat_count),
            }
            db["live_rooms_for_this_host"] = await room_repo.count_live_rooms_for_user(
                session, found.host_user_id
            )

    record("debug_room_detail", room=code.upper(), in_memory=live is not None, found=db is not None)
    return {"room": code.upper(), "in_memory": live, "database": db}


@router.get("/events")
async def events(limit: int = 60, room: str | None = None, kind: str | None = None) -> dict[str, Any]:
    """The recent-event buffer: client messages, socket lifecycle, rejections."""
    return {"events": recent(limit=max(1, min(limit, 200)), room=room, kind=kind)}


@router.post("/events/clear")
async def clear_events() -> dict[str, str]:
    """Empty the buffer so the next reproduction starts from a clean slate."""
    clear()
    return {"status": "cleared"}