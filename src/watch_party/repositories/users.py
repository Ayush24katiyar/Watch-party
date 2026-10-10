"""User repository: anonymous identity (D-1, S-1).

The server issues a uuid + random token; only the SHA-256 hash of the token is
stored, and verification is constant-time (S-1). Tokens are never logged (S-2).
"""

import hashlib
import hmac
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watch_party.db.models import User


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_user(session: AsyncSession) -> tuple[uuid.UUID, str]:
    """Create an anonymous identity; returns (user_id, token) - the token is
    shown to the client exactly once."""
    user_id = uuid.uuid4()
    token = secrets.token_urlsafe(32)
    session.add(User(id=user_id, token_hash=hash_token(token)))
    await session.commit()
    return user_id, token


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def verify_token(session: AsyncSession, user_id: uuid.UUID, token: str) -> bool:
    """Constant-time comparison of the token hash (S-1)."""
    user = await get_user(session, user_id)
    if user is None:
        return False
    return hmac.compare_digest(user.token_hash, hash_token(token))
