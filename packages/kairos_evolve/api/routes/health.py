"""Health + readiness endpoints. Bypass envelope verification."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    pool = request.app.state.pool
    async with pool.connection() as conn:
        cur = conn.cursor()
        try:
            await cur.execute("SELECT 1")
            await cur.fetchone()
        finally:
            await cur.close()
    return {"status": "ok", "db": "ok"}
