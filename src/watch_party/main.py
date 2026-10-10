from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from watch_party.api.routes import router as api_router
from watch_party.config import get_settings
from watch_party.db.engine import engine
from watch_party.ws.endpoint import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Phase 1+: WebSocket foundation (/ws/{code}).
    app.include_router(ws_router)
    # Phase 2: identity and rooms over REST.
    app.include_router(api_router)

    return app


app = create_app()
