"""REST routes (architecture section 8.1).

REST creates/checks rooms; live events ride the WebSocket (D-3). Credentials
travel in headers, never in URLs (D-5), and tokens are never logged (S-2).
"""

import uuid

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from watch_party.api.rate_limit import IpRateLimiter
from watch_party.config import get_settings
from watch_party.db.engine import SessionLocal
from watch_party.repositories import rooms as room_repo
from watch_party.repositories import users as user_repo
from watch_party.repositories.rooms import RoomLimitExceeded

router = APIRouter(prefix="/api")

# S-8: 30/min on lookups and identity creation. S-9: 5/min on room creation.
_identity_limiter = IpRateLimiter(get_settings().rest_rate_limit_per_minute)
_lookup_limiter = IpRateLimiter(get_settings().rest_rate_limit_per_minute)
_creation_limiter = IpRateLimiter(get_settings().room_creation_rate_limit_per_minute)


def reset_rate_limiters() -> None:
    """Test hook: called between tests so suites are not throttled by earlier tests."""
    _identity_limiter.reset()
    _lookup_limiter.reset()
    _creation_limiter.reset()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many_requests() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": {"code": "rate_limited", "message": "Too many requests; slow down."}},
    )


async def _authenticate(user_id: str | None, token: str | None) -> uuid.UUID:
    """X-User-Id / X-User-Token header auth (8.1); constant-time token compare (S-1)."""
    if not user_id or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Missing identity headers."},
        )
    try:
        parsed = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Malformed user id."},
        ) from None
    async with SessionLocal() as session:
        if not await user_repo.verify_token(session, parsed, token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "unauthorized", "message": "Authentication failed."},
            )
    return parsed


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_identity(request: Request) -> dict[str, str]:
    """Issue an anonymous identity: {userId, token}. The token is shown once (D-1)."""
    if not _identity_limiter.allow(_client_ip(request)):
        return _too_many_requests()
    async with SessionLocal() as session:
        user_id, token = await user_repo.create_user(session)
    return {"userId": str(user_id), "token": token}


@router.post("/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(
    request: Request,
    x_user_id: str | None = Header(default=None),
    x_user_token: str | None = Header(default=None),
) -> dict[str, str]:
    """Create a room; the caller becomes host (5.2). Returns {code}."""
    user_id = await _authenticate(x_user_id, x_user_token)
    if not _creation_limiter.allow(_client_ip(request)):
        return _too_many_requests()
    async with SessionLocal() as session:
        try:
            room = await room_repo.create_room(session, user_id)
        except RoomLimitExceeded:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": {
                        "code": "room_limit",
                        "message": "Too many live rooms for this user.",
                    }
                },
            )
    return {"code": room.code}


@router.get("/rooms/{code}")
async def check_room(request: Request, code: str) -> dict[str, object]:
    """Pre-check before joining (5.2): {code, joinable, reason?}.

    Missing and closed rooms look identical (generic not_found, S-8).
    """
    if not _lookup_limiter.allow(_client_ip(request)):
        return _too_many_requests()
    async with SessionLocal() as session:
        room = await room_repo.get_room_by_code(session, code)
        member_count = None
        if room is not None and room.status in ("open", "locked"):
            member_count = await room_repo.count_members(session, room.id)
    if room is None or room.status == "closed":
        return {"code": code.upper(), "joinable": False, "reason": "not_found"}
    if member_count is not None and member_count >= get_settings().max_room_size:
        return {"code": room.code, "joinable": False, "reason": "full"}
    if room.status == "locked":
        return {"code": room.code, "joinable": False, "reason": "locked"}
    return {"code": room.code, "joinable": True}
