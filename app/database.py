from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict:
    """On serverless (Vercel) each invocation may run in its own short-lived
    worker, so a persistent connection pool is worthless and actively harmful —
    idle pooled connections pile up against Postgres' connection limit. NullPool
    opens a connection per checkout and closes it on release. statement_cache_size=0
    keeps asyncpg working through a transaction-mode pooler (PgBouncer, Neon's
    pooled endpoint, Supabase's :6543), which can't keep server-side prepared
    statements across checkouts. SQLite (local dev) keeps SQLAlchemy's defaults."""
    url = settings.database_url
    if url.startswith("postgresql+asyncpg://"):
        return {"poolclass": NullPool, "connect_args": {"statement_cache_size": 0}}
    return {}


engine = create_async_engine(settings.database_url, echo=False, **_engine_kwargs())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db():
    async with SessionLocal() as session:
        yield session
