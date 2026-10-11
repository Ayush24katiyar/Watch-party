import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from watch_party.api.routes import router as api_router
from watch_party.config import get_settings
from watch_party.db.engine import engine
from watch_party.domain.room_manager import room_manager
from watch_party.logging import configure_logging, get_logger
from watch_party.ws.endpoint import router as ws_router

logger = get_logger()


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("watch-party starting up")
    sweeper = asyncio.create_task(_request_sweeper())
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass
        # 10.7: graceful shutdown - tell every client to reconnect (1012).
        for connection in room_manager.all_connections():
            await connection.close(1012)
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

    return app


app = create_app()
