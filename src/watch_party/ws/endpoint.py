"""WebSocket endpoint: /ws/{code} (Phase 1 foundation).

Lifecycle per architecture 10.1/10.2/10.6: Origin check before accept, 5 s join
gate, validated receive loop, heartbeat, per-connection rate limiting.
"""

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from watch_party.config import Settings, get_settings
from watch_party.domain.rate_limit import TokenBucket
from watch_party.ws.router import MessageRouter
from watch_party.ws.schemas import client_message_adapter

router = APIRouter()


def _origin_allowed(origin: str | None, settings: Settings) -> bool:
    """S-3: CORS does not protect WebSockets; check Origin before accept.

    A wrong Origin is always rejected. A *missing* Origin is rejected unless
    ALLOW_MISSING_ORIGIN is true (local-only, for debuggers).
    """
    if origin is None:
        return settings.allow_missing_origin
    return origin in settings.allowed_origins


class Connection:
    """One WebSocket connection: join gate, receive loop, heartbeat, rate limits."""

    def __init__(self, websocket: WebSocket, code: str, settings: Settings) -> None:
        self._websocket = websocket
        self.code = code  # room code from the path; validated in Phase 2
        self._settings = settings
        self._router = MessageRouter(self)
        self._joined = False
        self._closing = False
        self._last_pong = time.monotonic()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._bucket = TokenBucket(settings.ws_rate_limit_other_per_second)
        self._invalid_times: list[float] = []
        self._rate_limited_times: list[float] = []

    # ---- lifecycle ----

    async def run(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            try:
                # 10.1: a valid join_room must arrive within join_timeout_seconds.
                await asyncio.wait_for(self._join_gate(), timeout=self._settings.join_timeout_seconds)
            except asyncio.TimeoutError:
                await self.close(4007)
                return
            while not self._closing:
                raw = await self._websocket.receive_text()
                await self._process(raw)
        except WebSocketDisconnect:
            pass
        finally:
            await self._shutdown()

    async def _join_gate(self) -> None:
        """Wait for a valid join_room. Malformed / wrong-type input is an error,
        not a close (17); the 5 s gate is what enforces 4007 (8.5)."""
        while not self._joined and not self._closing:
            raw = await self._websocket.receive_text()
            await self._process_pre_join(raw)

    async def _process_pre_join(self, raw: str) -> None:
        if not await self._check_limits(raw):
            if self._closing:
                # Size/abuse close already sent; abort the gate.
                raise WebSocketDisconnect(1000)
            return  # soft error (rate limit): keep waiting for a valid join_room
        try:
            message = client_message_adapter.validate_python(json.loads(raw))
        except (json.JSONDecodeError, ValidationError):
            await self.reject("invalid_message", "Expected a valid join_room message.")
            return
        if message.type != "join_room":
            await self.reject("invalid_message", "First message must be join_room.")
            return
        # Phase 1: schema validation only. Token auth and room lookup arrive in Phase 2 (10.1).
        self._joined = True

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
        # Kept for the router dispatch table; the join gate is _process_first.
        self._joined = True

    async def on_pong(self, payload: dict[str, Any], request_id: str | None) -> None:
        self._last_pong = time.monotonic()

    async def on_echo(self, payload: dict[str, Any], request_id: str | None) -> None:
        # TEMPORARY dev-only event (8.2); removed at the end of Phase 2.
        await self.send({"type": "echo", "payload": payload})

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
        await self.send({"type": "error", "payload": payload})
        if code != "rate_limited":
            # S-5: 10 invalid messages in 60 s -> close 4009.
            self._invalid_times.append(time.monotonic())
            if self._count_recent(self._invalid_times) >= self._settings.ws_max_invalid_per_window:
                await self.close(4009)

    async def close(self, code: int) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            await self._websocket.close(code=code)
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def _shutdown(self) -> None:
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

    # ---- abuse bookkeeping ----

    def _count_recent(self, times: list[float]) -> int:
        cutoff = time.monotonic() - self._settings.ws_abuse_window_seconds
        return sum(1 for moment in times if moment >= cutoff)


@router.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str) -> None:
    settings = get_settings()
    if not _origin_allowed(websocket.headers.get("origin"), settings):
        # Reject before accept: denied upgrade (HTTP 403), no socket is opened (S-3).
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await Connection(websocket, code, settings).run()
