"""psycopg-backed connection pool factory.

Connection pool is owned by the FastAPI app's lifespan and injected into
routes via Depends(). Pool config is kept small because each service instance
handles modest concurrency (one pool per App Runner instance; revisit sizing
for the App Runner profile during migration).

The DSN is a generic Postgres conninfo (RDS in prod; any Postgres in dev/test),
so this adapter is platform-neutral.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from psycopg_pool import AsyncConnectionPool


async def build_pool(
    database_url: str, *, min_size: int = 1, max_size: int = 8
) -> AsyncConnectionPool:
    """Open an async psycopg connection pool, ready for use."""
    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=min_size,
        max_size=max_size,
        open=False,
    )
    await pool.open(wait=True, timeout=30.0)
    return pool


@asynccontextmanager
async def acquire(pool: AsyncConnectionPool) -> AsyncIterator[psycopg.AsyncConnection]:
    """Acquire a connection; returns it to the pool on exit."""
    async with pool.connection() as conn:
        yield conn


__all__ = ["acquire", "build_pool"]
