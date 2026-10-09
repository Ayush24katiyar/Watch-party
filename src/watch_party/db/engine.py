from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from watch_party.config import get_settings

# The engine connects lazily, so the app starts fine before Postgres is up.
engine = create_async_engine(get_settings().database_url)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
