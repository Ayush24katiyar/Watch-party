"""SQLAlchemy models (architecture section 12).

Tables: users, rooms, room_members. This module is the ONLY place that defines
table structure; repositories are the only place that touches it.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Only the SHA-256 hash of the token is stored (S-1, S-2).
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 6 chars from the code alphabet; case-insensitive on lookup (8.1).
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    host_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # open | locked | closed (12). Closed rooms are reported as not_found (S-8).
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    # Playback snapshot (D-22); consumed from Phase 5, columns exist from now.
    video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    play_state: Mapped[str] = mapped_column(String(16), default="paused", nullable=False)
    position: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Sanitised server-side (control characters stripped, <= 500 chars).
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RoomMember(Base):
    # Composite primary key already enforces one row per (room, user).
    __tablename__ = "room_members"

    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # Usernames are per-room (12) and unique within a room (R-3).
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    # host | moderator | participant (9)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Removed users cannot rejoin (D-16).
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
