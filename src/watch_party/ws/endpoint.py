"""WebSocket endpoint: /ws/{code}.

Phase 1: Origin check, join gate, validated receive loop, heartbeat, limits.
Phase 2: real join_room - token auth (S-1), room restore from the DB (10.1, D-22),
banned/locked/full/duplicate checks, room_joined + user_joined broadcasts.

The join flow is split into small steps (each under 10 cyclomatic complexity)
so Phase 3/4 can extend membership and host tools without growing one giant method.
"""

import asyncio
import json
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from watch_party.config import Settings, get_settings
from watch_party.db.engine import SessionLocal
from watch_party.debug.recorder import record
from watch_party.domain.participant import Participant
from watch_party.domain.rate_limit import TokenBucket
from watch_party.domain.roles import Role
from watch_party.domain.room import Room
from watch_party.domain.room_manager import room_manager
from watch_party.domain.usernames import unique_username
from watch_party.logging import get_logger
from watch_party.repositories import chat as chat_repo
from watch_party.repositories import members as member_repo
from watch_party.repositories import rooms as room_repo
from watch_party.repositories import users as user_repo
from watch_party.ws.handlers import roles as role_handlers
from watch_party.ws.router import MessageRouter
from watch_party.ws.schemas import JoinRoomPayload, client_message_adapter

router = APIRouter()

logger = get_logger()

# The room creator's member row gets this placeholder until their first join.
ROOM_CREATOR_PLACEHOLDER = "host"


def _origin_allowed(origin: str | None, settings: Settings) -> bool:
    """S-3: CORS does not protect WebSockets; check Origin before accept."""
    if origin is None:
        return settings.allow_missing_origin
    return origin in settings.allowed_origins


class Connection:
    """One WebSocket connection: join gate, receive loop, heartbeat, rate limits."""

    def __init__(self, websocket: WebSocket, code: str, settings: Settings) -> None:
        self._websocket = websocket
        self.code = code
        self._settings = settings
        self._router = MessageRouter(self)
        room_manager.register_connection(self)
        self._joined = False
        self._closing = False
        self._last_pong = time.monotonic()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._bucket = TokenBucket(settings.ws_rate_limit_other_per_second)
        # S-7: chat and reactions get their own, tighter buckets.
        self._chat_bucket = TokenBucket(settings.chat_rate_limit_per_second)
        self._reaction_bucket = TokenBucket(settings.reaction_rate_limit_per_second)
        self._invalid_times: list[float] = []
        self._rate_limited_times: list[float] = []
        self.room: Room | None = None
        self.you: Participant | None = None

    @property
    def chat_bucket(self):
        return self._chat_bucket

    @property
    def reaction_bucket(self):
        return self._reaction_bucket

    @property
    def settings(self) -> Settings:
        return self._settings

    # ---- lifecycle ----

    async def run(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            try:
                # 10.1: a valid join_room must arrive within join_timeout_seconds.
                await asyncio.wait_for(self._join_gate(), timeout=self._settings.join_timeout_seconds)
            except TimeoutError:
                await self.close(4007)
                return
            while not self._closing:
                raw = await self._websocket.receive_text()
                await self._process(raw)
        except (WebSocketDisconnect, TimeoutError):
            pass
        finally:
            await self._shutdown()
            await self._depart()

    async def _join_gate(self) -> None:
        """Wait for a valid join_room. Malformed / wrong-type input is an error,
        not a close (17); the 5 s gate is what enforces 4007 (8.5)."""
        while not self._joined and not self._closing:
            raw = await self._websocket.receive_text()
            await self._process_pre_join(raw)

    # ---- join (Phase 2), one step per method ----

    async def _process_pre_join(self, raw: str) -> None:
        if not await self._check_limits(raw):
            if self._closing:
                # Size/abuse close already sent; abort the gate.
                raise WebSocketDisconnect(1000)
            return
        try:
            message = client_message_adapter.validate_python(json.loads(raw))
        except (json.JSONDecodeError, ValidationError):
            await self.reject("invalid_message", "Expected a valid join_room message.")
            return
        if message.type != "join_room":
            await self.reject("invalid_message", "First message must be join_room.")
            return

        payload = message.payload
        user_id = await self._authenticate(payload)
        if user_id is None:
            return

        room = await self._resolve_and_validate_room(payload.room_id, user_id)
        if room is None:
            return

        you = await self._assign_member(room, payload, user_id)
        if you is None:
            return

        self.room = room
        self.you = you
        await self.send({"type": "room_joined", "payload": await self._joined_payload()})
        await room.broadcast(
            {
                "type": "user_joined",
                "payload": {
                    "username": you.username,
                    "userId": you.user_id,
                    "role": you.role.value,
                    "participants": room.participant_snapshots(),
                },
            },
            exclude_user_id=you.user_id,
        )
        self._joined = True
        # Someone is online again: any empty-room timer is void (10.5).
        room_manager.cancel_cleanup(room)
        # A returning host cancels their own grace period (D-15).
        if you.user_id == room.host_user_id:
            room_manager.cancel_host_grace(room)

    async def _authenticate(self, payload: JoinRoomPayload) -> UUID | None:
        """S-1: the token proves identity; a self-reported userId is never trusted."""
        try:
            user_id = UUID(payload.user_id)
        except ValueError:
            await self.reject("unauthorized", "Malformed user id.")
            await self.close(4002)
            return None
        async with SessionLocal() as session:
            authorized = await self.run_db(user_repo.verify_token(session, user_id, payload.token))
        if not authorized:
            await self.reject("unauthorized", "Authentication failed.")
            await self.close(4002)
            return None
        return user_id

    async def _resolve_and_validate_room(self, room_id: str, user_id: UUID) -> Room | None:
        """Memory first, else lazy restore (10.1, D-22); banned members are refused (D-16)."""
        room = await self._resolve_room(room_id)
        if room is None:
            # Missing and closed rooms look identical (S-8).
            await self.reject("not_found", "Room not found or closed.")
            await self.close(4001)
            return None
        async with SessionLocal() as session:
            member_row = await self.run_db(member_repo.get_member(session, room.require_db_id(), user_id))
        if member_row is not None and member_row.is_banned:
            await self.reject("forbidden", "You were removed from this room.")
            await self.close(4003)
            return None
        return room

    async def _assign_member(
        self, room: Room, payload: JoinRoomPayload, user_id: UUID
    ) -> Participant | None:
        """Returning member or new participant, attached to this connection (10.1, D-13).

        The lock guards in-memory state only (B-014): DB writes and the close of
        a replaced socket happen after it is released, so a slow query cannot
        stall every other join in the room.
        """
        pending_username: str | None = None
        is_new_member = False
        previous: Connection | None = None
        participant: Participant | None = None

        async with room.lock:
            member = room.participants.get(str(user_id))
            if member is not None:
                participant = member
                # Returning members keep their stored name (10.3), except the
                # creator's placeholder, replaced by the name they choose now.
                if member.username == ROOM_CREATOR_PLACEHOLDER:
                    member.username = unique_username(
                        payload.username,
                        [p.username for p in room if p.user_id != member.user_id],
                    )
                    pending_username = member.username
            else:
                participant = await self._add_participant(room, payload, user_id)
                if participant is None:
                    return None
                pending_username = participant.username
                is_new_member = True
            previous = participant.connection
            participant.connection = self

        # Outside the lock: persistence and the 4004 close.
        async with SessionLocal() as session:
            if is_new_member:
                await self.run_db(
                    member_repo.add_member(
                        session, room.require_db_id(), user_id, pending_username or ""
                    )
                )
            elif pending_username is not None:
                await self.run_db(
                    member_repo.update_username(
                        session, room.require_db_id(), user_id, pending_username
                    )
                )
        if previous is not None and previous is not self:
            await previous.close(4004)
        return participant

    async def _add_participant(
        self, room: Room, payload: JoinRoomPayload, user_id: UUID
    ) -> Participant | None:
        """New member, in memory only: locked (4006) and full (4005) are checked
        before any state change. Persistence happens outside the room lock (B-014)."""
        if room.locked:
            await self.reject("room_locked", "Room is locked.")
            await self.close(4006)
            return None
        if room.is_full(self._settings.max_room_size):
            await self.reject("room_full", "Room is full.")
            await self.close(4005)
            return None
        username = unique_username(payload.username, [p.username for p in room])
        participant = Participant(str(user_id), username, Role.PARTICIPANT, time.time())
        room.add(participant)
        return participant

    async def _resolve_room(self, code: str) -> Room | None:
        room = room_manager.get(code)
        if room is not None:
            return room
        # B-010: serialize restores per code. Without this, two users joining the
        # same DB-backed room at once both miss the cache, both build a Room from
        # the snapshot, and the second register() discards the first's members.
        async with room_manager.restore_lock(code):
            room = room_manager.get(code)
            if room is not None:
                return room  # the other join finished first; reuse its room
            return await self._build_room(code)

    async def _build_room(self, code: str) -> Room | None:
        async with SessionLocal() as session:
            db_room = await self.run_db(room_repo.get_live_room_by_code(session, code))
            if db_room is None:
                return None
            rows = await self.run_db(member_repo.get_members(session, db_room.id))
            members = [
                {
                    "user_id": str(row.user_id),
                    "username": row.username,
                    "role": row.role,
                    "joined_ts": row.joined_at.timestamp(),
                }
                for row in rows
                if not row.is_banned
            ]
            snapshot = {
                "code": db_room.code,
                "host_user_id": str(db_room.host_user_id),
                "status": db_room.status,
                "members": members,
                "video_state": {
                    "video_id": db_room.video_id,
                    "position": db_room.position,
                    "seq": db_room.seq,
                },
                "db_id": db_room.id,
            }
        return room_manager.build_from_snapshot(**snapshot)

    # ---- steady state ----

    async def _joined_payload(self) -> dict[str, Any]:
        """The `room_joined` payload (8.3): full roster, playback state, history.

        Pending requests are mapped to the camelCase wire shape (D-18); the
        store keeps snake_case keys, so sending the raw dicts broke the client.
        """
        room, you = self.room, self.you
        assert room is not None and you is not None  # only called after joining
        recent_chat: list[dict[str, Any]] = []
        if room.db_id is not None:
            async with SessionLocal() as session:
                recent_chat = await chat_repo.recent_messages(session, room.require_db_id())
        return {
            "you": you.snapshot(),
            "participants": room.participant_snapshots(),
            "state": room.state_snapshot(),
            "locked": room.locked,
            "pendingRequests": [
                {
                    "requestId": request["requestId"],
                    "userId": request["user_id"],
                    "username": request["username"],
                    "action": request["action"],
                    "payload": request["payload"],
                    "expiresAt": request["expiresAt"],
                }
                for request in room.pending_requests.values()
            ],
            "recentChat": recent_chat,
        }

    async def _process(self, raw: str) -> None:
        if not await self._check_limits(raw):
            return
        await self._router.route(raw)

    async def _check_limits(self, raw: str) -> bool:
        """Size cap + rate limit, shared by the first and live message paths."""
        # Layer 1 of the size cap (S-6): app level, always on.
        if len(raw.encode("utf-8")) > self._settings.ws_max_size_bytes:
            await self.reject("invalid_message", "Message exceeds the size limit.")
            await self.close(4007)
            return False

        if not self._bucket.consume():
            # S-7: burst -> error; sustained abuse -> close 4008.
            self._rate_limited_times.append(time.monotonic())
            await self.reject("rate_limited", "Too many messages; slow down.")
            if self._count_recent(self._rate_limited_times) >= self._settings.ws_max_invalid_per_window:
                await self.close(4008)
            return False

        return True

    # ---- handlers (called by MessageRouter) ----

    async def on_join_room(self, payload: dict[str, Any], request_id: str | None) -> None:
        # The join gate is _process_pre_join; this is the live connection
        # answering a second join_room. Re-joining is not an error state, so
        # answer with the current state instead of silently accepting (B-012).
        await self.send({"type": "room_joined", "payload": await self._joined_payload()})

    async def on_pong(self, payload: dict[str, Any], request_id: str | None) -> None:
        self._last_pong = time.monotonic()

    async def on_leave_room(self, payload: dict[str, Any], request_id: str | None) -> None:
        """10.3: intentional leave - announce, reassign host immediately, close cleanly."""
        await self._depart(intentional=True)
        self.room = None
        self.you = None
        await self.close(1000)

    # ---- departure (Phase 3/4) ----

    async def _depart(self, intentional: bool = False) -> None:
        """Membership persists offline (10.3): detach, announce `user_left`, handle a
        departing host (grace vs immediate, D-15), and schedule empty-room cleanup (10.5).
        Skipped when a newer connection replaced this one (D-14)."""
        room, you = self.room, self.you
        if room is None or you is None:
            return
        if you.connection is not self:
            return
        you.connection = None
        if self._joined:
            await room.broadcast(
                {
                    "type": "user_left",
                    "payload": {
                        "username": you.username,
                        "userId": you.user_id,
                        "participants": room.participant_snapshots(),
                    },
                }
            )
        if self._joined and you.role == Role.HOST:
            await self._handle_host_departure(room, intentional)
        self._maybe_schedule_cleanup(room)

    async def _handle_host_departure(self, room: Room, intentional: bool) -> None:
        """D-15/10.3: a page refresh must not cost host status, so an unexpected
        disconnect starts the grace timer; an intentional leave reassigns at once."""
        if intentional:
            await role_handlers.reassign_host(self)
            return
        room_manager.schedule_host_grace(
            room,
            self._settings.host_grace_seconds,
            lambda _room: role_handlers.reassign_host(self),
        )

    def _maybe_schedule_cleanup(self, room: Room) -> None:
        if room.has_online_participants():
            room_manager.cancel_cleanup(room)
            return
        room_manager.schedule_cleanup(
            room, self._settings.empty_room_ttl_seconds, self._on_room_expired
        )

    # ---- playback snapshots (D-22) ----

    def schedule_snapshot(self, room: Room) -> None:
        """Debounced: rapid playback changes coalesce into one DB write."""
        room_manager.schedule_snapshot(
            room, self._settings.playback_debounce_seconds, self._save_snapshot
        )

    async def _save_snapshot(self, room: Room) -> None:
        if room.db_id is None:
            return
        state = room.video_state
        try:
            async with SessionLocal() as session:
                await self.run_db(
                    room_repo.save_state_snapshot(
                        session,
                        room.db_id,
                        state["video_id"],
                        state["play_state"],
                        state["position"],
                        state["seq"],
                    )
                )
        except (TimeoutError, OSError):
            pass  # a later state change will retry the snapshot

    async def _on_room_expired(self, room: Room) -> None:
        """10.5: empty for the TTL -> closed in the DB and dropped from memory."""
        if room.db_id is not None:
            try:
                async with SessionLocal() as session:
                    await self.run_db(room_repo.set_room_status(session, room.require_db_id(), "closed"))
            except (TimeoutError, OSError):
                pass  # DB unreachable: still forget; a later join restores from the DB row
        # 8.3: tell any remaining connections, then close.
        await room.broadcast({"type": "room_closed", "payload": {"reason": "empty"}})
        room_manager.forget(room.code)

    # ---- wire helpers ----

    async def send(self, event: dict[str, Any]) -> None:
        try:
            await self._websocket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            self._closing = True

    async def reject(self, code: str, message: str, request_id: str | None = None) -> None:
        payload: dict[str, Any] = {"code": code, "message": message}
        if request_id is not None:
            payload["requestId"] = request_id
        record(
            "reject",
            room=self.room.code if self.room else "",
            user=self.you.user_id if self.you else None,
            code=code,
            request_id=request_id,
        )
        await self.send({"type": "error", "payload": payload})
        if code != "rate_limited":
            # S-5: 10 invalid messages in 60 s -> close 4009.
            self._invalid_times.append(time.monotonic())
            if self._count_recent(self._invalid_times) >= self._settings.ws_max_invalid_per_window:
                await self.close(4009)

    async def close(self, code: int) -> None:
        record(
            "close",
            room=self.room.code if self.room else "",
            user=self.you.user_id if self.you else None,
            code=code,
        )
        if self._closing:
            return
        self._closing = True
        try:
            await self._websocket.close(code=code)
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def _shutdown(self) -> None:
        room_manager.unregister_connection(self)
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        try:
            await self._websocket.close()
        except (WebSocketDisconnect, RuntimeError):
            pass

    # ---- heartbeat ----

    async def _heartbeat_loop(self) -> None:
        """10.6: ping every 20 s; no pong within 40 s -> zombie, close 1001 (8.5)."""
        try:
            while not self._closing:
                await asyncio.sleep(self._settings.ws_ping_interval_seconds)
                if time.monotonic() - self._last_pong > self._settings.ws_ping_timeout_seconds:
                    await self.close(1001)
                    return
                await self.send({"type": "ping", "payload": {}})
        except asyncio.CancelledError:
            pass

    # ---- helpers ----

    async def run_db(self, coro: Any) -> Any:
        """Bound every DB call (R-6); public so handlers can use it: a hung query must not hold the room lock."""
        return await asyncio.wait_for(coro, timeout=self._settings.ws_db_timeout_seconds)

    def _count_recent(self, times: list[float]) -> int:
        cutoff = time.monotonic() - self._settings.ws_abuse_window_seconds
        return sum(1 for moment in times if moment >= cutoff)


@router.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str) -> None:
    settings = get_settings()
    client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    logger.info("WS /ws/%s upgrade requested (client=%s)", code.upper(), client)
    record("ws_open_attempt", room=code.upper(), client=client)
    if not _origin_allowed(websocket.headers.get("origin"), settings):
        # Reject before accept: denied upgrade (HTTP 403), no socket is opened (S-3).
        logger.warning("WS /ws/%s rejected: bad origin", code.upper())
        await websocket.close(code=1008)
        return

    await websocket.accept()
    logger.info("WS /ws/%s accepted (client=%s)", code.upper(), client)
    record("ws_accepted", room=code.upper(), client=client)
    try:
        await Connection(websocket, code, settings).run()
    finally:
        logger.info("WS /ws/%s connection closed (client=%s)", code.upper(), client)
        record("ws_closed", room=code.upper(), client=client)
