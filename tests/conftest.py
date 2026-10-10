"""Pytest configuration.

Integration tests run against a dedicated `watchparty_test` database: the URL is
forced via env (which beats .env) before any app import, migrations run once per
session, and each test starts from empty tables (see PRODUCTION.md decision).
"""

import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://watch:watch@127.0.0.1:5432/watchparty_test"
# Same engine is used from several event loops in tests -> no pooled connections.
os.environ.setdefault("DB_NULL_POOL", "true")
# Fast, deterministic WebSocket settings for tests (architecture values /10).
os.environ.setdefault("JOIN_TIMEOUT_SECONDS", "0.3")
os.environ.setdefault("WS_PING_INTERVAL_SECONDS", "0.2")
os.environ.setdefault("WS_PING_TIMEOUT_SECONDS", "0.5")
os.environ.setdefault("WS_RATE_LIMIT_OTHER_PER_SECOND", "5")
os.environ.setdefault("WS_MAX_SIZE_BYTES", "200")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("ALLOW_MISSING_ORIGIN", "false")

import concurrent.futures
import os as _os

import anyio
import pytest
from sqlalchemy import text

TEST_ORIGIN = "http://localhost:5173"

# A TestClient receive blocks forever if the server never sends/closes; bound it
# so a regression shows up as a failed test instead of a hung suite.
RECEIVE_TIMEOUT_SECONDS = 10.0


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database():
    """Upgrade the test DB once per session: exercises the real migration path."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
async def clean_state():
    """Every test starts from empty tables, an empty RoomManager and fresh limiters."""
    from watch_party.api.routes import reset_rate_limiters
    from watch_party.db.engine import engine
    from watch_party.domain.room_manager import room_manager

    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE room_members, rooms, users RESTART IDENTITY CASCADE")
        )
    room_manager.reset()
    reset_rate_limiters()
    yield
    room_manager.reset()
    # Pooled connections are loop-bound; dispose so sync tests can use anyio.run.
    await engine.dispose()


@pytest.fixture()
def make_user_with_room():
    """Sync factory: create a user + room via the repositories (what REST would do)."""

    def _make(username: str = "host") -> dict:
        from watch_party.db.engine import SessionLocal
        from watch_party.repositories import rooms as room_repo
        from watch_party.repositories import users as user_repo

        async def _create() -> dict:
            async with SessionLocal() as session:
                user_id, token = await user_repo.create_user(session)
                room = await room_repo.create_room(session, user_id)
            return {"userId": str(user_id), "token": token, "roomCode": room.code}

        return anyio.run(_create)

    return _make


@pytest.fixture()
def room_ops():
    """Sync admin helpers: close/lock rooms and ban members."""

    def _run(coro):
        return anyio.run(coro)

    def set_status(room_code: str, status: str) -> None:
        from uuid import UUID

        from watch_party.db.engine import SessionLocal
        from watch_party.repositories import rooms as room_repo

        async def _update() -> None:
            async with SessionLocal() as session:
                room = await room_repo.get_room_by_code(session, room_code)
                if room is not None:
                    await room_repo.set_room_status(session, UUID(str(room.id)), status)

        _run(_update)

    def ban(room_code: str, user_id: str) -> None:
        from uuid import UUID

        from watch_party.db.engine import SessionLocal
        from watch_party.repositories import members as member_repo
        from watch_party.repositories import rooms as room_repo

        async def _update() -> None:
            async with SessionLocal() as session:
                room = await room_repo.get_room_by_code(session, room_code)
                if room is not None:
                    await member_repo.ban_member(
                        session, UUID(str(room.id)), UUID(user_id)
                    )

        _run(_update)

    return {"set_status": set_status, "ban": ban}


def join_payload(room_code: str, user_id: str, token: str, username: str = "player") -> dict:
    return {
        "type": "join_room",
        "payload": {
            "roomId": room_code,
            "username": username,
            "userId": user_id,
            "token": token,
        },
    }


def receive_json_bounded(websocket, timeout: float = RECEIVE_TIMEOUT_SECONDS) -> dict:
    """receive_json that fails instead of hanging if nothing ever arrives."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(websocket.receive_json)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise AssertionError(f"no server message within {timeout}s") from exc


def receive_pings(websocket, count: int) -> None:
    """Wait for `count` server pings, answering each with pong (10.6).

    Cannot use recv_until: that helper consumes pings, so waiting *for* a ping
    would never return.
    """
    for _ in range(count):
        while True:
            event = receive_json_bounded(websocket)
            if event.get("type") == "ping":
                break
        websocket.send_json({"type": "pong", "payload": {}})


def recv_until(websocket, predicate):
    """Receive server events, answering pings, until `predicate(event)` matches."""
    while True:
        event = receive_json_bounded(websocket)
        if event.get("type") == "ping":
            websocket.send_json({"type": "pong", "payload": {}})
            continue
        if predicate(event):
            return event


def drain_until_close(websocket):
    """Consume events (ignoring pings) until the server closes the socket."""
    while True:
        websocket.receive_text()
