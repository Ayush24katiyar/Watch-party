from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from watch_party.config import get_settings

_settings = get_settings()
_pool_kwargs = {"poolclass": NullPool} if _settings.db_null_pool else {}

# The engine connects lazily, so the app starts fine before Postgres is up.
engine = create_async_engine(_settings.database_url, **_pool_kwargs)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
