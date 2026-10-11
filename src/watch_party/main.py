import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from watch_party.api.routes import router as api_router
from watch_party.config import get_settings
from watch_party.db.engine import SessionLocal, engine
from watch_party.debug.routes import router as debug_router
from watch_party.domain.room_manager import room_manager
from watch_party.logging import configure_logging, get_logger
from watch_party.repositories import rooms as room_repo
from watch_party.ws.endpoint import router as ws_router

logger = get_logger()

# Per-connection ceiling during shutdown, so a dead peer cannot hang the exit.
CLOSE_TIMEOUT_SECONDS = 2.0
# How often the stale-room reaper runs.
REAP_INTERVAL_SECONDS = 60.0


async def _request_sweeper() -> None:
    """Phase 6: broadcast expiry for pending requests past their TTL (8.3)."""
    while True:
        await asyncio.sleep(get_settings().request_sweep_seconds)
        for room in room_manager.all_rooms():
            for expired in room.collect_expired_requests():
                await room.broadcast(
                    {
                        "type": "request_resolved",
                        "payload": {
                            "requestId": expired["requestId"],
                            "approved": False,
                            "reason": "expired",
                        },
                    }
                )


async def _room_reaper() -> None:
    """Close rooms that are live in the database but dead in memory (10.5).

    The in-memory empty-room timer only runs once somebody has joined and left.
    A room created over REST and never joined - or one whose timer was lost when
    the process restarted - would otherwise stay 'open' forever and count
    against the creator's live-room limit (S-9).
    """
    settings = get_settings()
    while True:
        await asyncio.sleep(REAP_INTERVAL_SECONDS)
        cutoff = datetime.now(UTC) - timedelta(seconds=settings.empty_room_ttl_seconds)
        try:
            async with SessionLocal() as session:
                stale = await room_repo.find_reapable_rooms(session, cutoff)
                for room in stale:
                    # Never close a room somebody is actually sitting in.
                    live = room_manager.get(room.code)
                    if live is not None and live.has_online_participants():
                        continue
                    await room_repo.set_room_status(session, room.id, "closed")
                    logger.info("reaped stale room code=%s", room.code)
        except (TimeoutError, OSError):
            # DB unreachable; try again on the next tick.
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("watch-party starting up")
    sweeper = asyncio.create_task(_request_sweeper())
    reaper = asyncio.create_task(_room_reaper())
    try:
        yield
    finally:
        sweeper.cancel()
        reaper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass
        try:
            await reaper
        except asyncio.CancelledError:
            pass
        # 10.7: graceful shutdown - tell every client to reconnect (1012).
        # Bounded: one wedged socket must not stall engine.dispose() forever.
        for connection in room_manager.all_connections():
            try:
                await asyncio.wait_for(connection.close(1012), timeout=CLOSE_TIMEOUT_SECONDS)
            except TimeoutError:
                logger.warning("shutdown: timed out closing a connection")
            except Exception:
                logger.warning("shutdown: error closing a connection", exc_info=True)
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="watch-party", lifespan=lifespan)

    # Explicit allow-list (never "*" with credentials): used for both REST and the WebSocket Origin check.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Terminal trace for every HTTP route hit: method, path, status, duration.
    @app.middleware("http")
    async def log_request(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "HTTP %s %s -> error (%.1fms)",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "HTTP %s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Phase 1+: WebSocket foundation (/ws/{code}).
    app.include_router(ws_router)
    # Phase 2: identity and rooms over REST.
    app.include_router(api_router)

    # Local diagnostics: live room state + recent events, so a browser problem
    # can be pinned down from the terminal. Off in production.
    if settings.debug_endpoints:
        app.include_router(debug_router)
        logger.info("debug endpoints enabled at /debug (disable with DEBUG_ENDPOINTS=false)")

    return app


app = create_app()
