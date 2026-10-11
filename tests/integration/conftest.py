"""Integration fixtures (DB-backed; Postgres must be running).

Unit tests never import this module, so `uv run pytest tests/unit` works with
Docker stopped. The `client` fixture is defined once here instead of
copy-pasted per file. The host+guest pair fixture uses ExitStack so a failed
join still closes every socket it opened.
"""

import concurrent.futures
import contextlib

import anyio
import pytest
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from tests.conftest import TEST_ORIGIN, join_payload, recv_until


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
def client():
    from fastapi.testclient import TestClient

    from watch_party.config import get_settings
    from watch_party.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


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


class _JoinedPair:
    """Host + guest, both joined to the host's room.

    Context-managed with ExitStack: if the second join fails, the first socket
    is still closed instead of leaking into teardown.
    """

    def __init__(self, client, host: dict, guest: dict) -> None:
        self._client = client
        self.host = host
        self.guest = guest
        self.code = host["roomCode"]
        self._stack = contextlib.ExitStack()

    def __enter__(self):
        try:
            self.ws_host = self._stack.enter_context(
                self._client.websocket_connect(
                    f"/ws/{self.code}", headers={"origin": TEST_ORIGIN}
                )
            )
            self.ws_host.send_json(
                join_payload(self.code, self.host["userId"], self.host["token"], "ayush")
            )
            recv_until(self.ws_host, lambda e: e.get("type") == "room_joined")
            self.ws_guest = self._stack.enter_context(
                self._client.websocket_connect(
                    f"/ws/{self.code}", headers={"origin": TEST_ORIGIN}
                )
            )
            self.ws_guest.send_json(
                join_payload(self.code, self.guest["userId"], self.guest["token"], "neha")
            )
            recv_until(self.ws_guest, lambda e: e.get("type") == "room_joined")
        except BaseException:
            self._stack.close()
            raise
        return self

    def __exit__(self, *args):
        # Sockets may already be server-closed; exiting again is harmless.
        # concurrent.futures.CancelledError means the app task died first
        # (TestClient exit raced server teardown) - also harmless here.
        try:
            self._stack.close()
        except (WebSocketDisconnect, RuntimeError, concurrent.futures.CancelledError):
            pass
        return False

    def send_host(self, type_: str, payload: dict) -> None:
        self.ws_host.send_json({"type": type_, "payload": payload})

    def send_guest(self, type_: str, payload: dict) -> None:
        self.ws_guest.send_json({"type": type_, "payload": payload})


@pytest.fixture()
def joined_pair(client, make_user_with_room):
    """Two users connected to the same room: (host, guest, ws_host, ws_guest)."""
    return _JoinedPair(client, make_user_with_room(), make_user_with_room())
