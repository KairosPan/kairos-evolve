"""Idempotency-Key header middleware.

After envelope_verify has run (so request.state.body_obj is set), this
middleware:
  - looks up the Idempotency-Key in kairos_audit.idempotency_keys
  - if hit & request_hash matches: returns cached response with X-Idempotent-Replay: true
  - if hit & request_hash differs: returns 409
  - if miss: runs handler, stores response in idempotency table for replay TTL

Applies to write methods only; same BYPASS_PATHS as envelope middleware.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from kairos_evolve.api.middleware.envelope_verify import BYPASS_PATHS, WRITE_METHODS


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in WRITE_METHODS or request.url.path in BYPASS_PATHS:
            return await call_next(request)

        key = request.headers.get("Idempotency-Key")
        if not key:
            return JSONResponse(
                {"detail": "Idempotency-Key header required"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Compute request_hash from the verified body the envelope middleware
        # stashed; if envelope middleware didn't run (programmer error), fall
        # back to raw body bytes.
        body_obj = getattr(request.state, "body_obj", None)
        if body_obj is not None:
            body_canon = json.dumps(body_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        else:
            body_canon = await request.body()
        request_hash = hashlib.sha256(body_canon).hexdigest()

        pool = request.app.state.pool
        clock = request.app.state.clock
        ttl = request.app.state.settings.idempotency_ttl

        async with pool.connection() as conn:
            cur = conn.cursor()
            try:
                await cur.execute(
                    """
                    SELECT request_hash, response_status, response_body_jsonb, expires_at
                      FROM kairos_audit.idempotency_keys
                     WHERE key = %s
                    """,
                    (key,),
                )
                row = await cur.fetchone()
            finally:
                await cur.close()

            if row is not None:
                stored_hash, status_code, body, expires_at = row
                if clock.now() < expires_at:
                    if stored_hash != request_hash:
                        return JSONResponse(
                            {"detail": f"Idempotency-Key collision: {key!r}"},
                            status_code=status.HTTP_409_CONFLICT,
                        )
                    return JSONResponse(
                        body or {},
                        status_code=status_code,
                        headers={"X-Idempotent-Replay": "true"},
                    )

            # Miss → run handler, then store response.
            response = await call_next(request)
            # Read response body to cache; rewrap so it can still stream out.
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk
            try:
                response_payload = (
                    json.loads(response_body.decode("utf-8")) if response_body else None
                )
            except json.JSONDecodeError:
                response_payload = None

            cur = conn.cursor()
            try:
                await cur.execute(
                    """
                    INSERT INTO kairos_audit.idempotency_keys
                        (key, request_hash, response_status, response_body_jsonb, created_at, expires_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (
                        key,
                        request_hash,
                        response.status_code,
                        json.dumps(response_payload) if response_payload is not None else None,
                        clock.now(),
                        clock.now() + ttl,
                    ),
                )
            finally:
                await cur.close()
            await conn.commit()

            return JSONResponse(
                response_payload or {},
                status_code=response.status_code,
                headers=dict(response.headers),
            )


__all__ = ["IdempotencyMiddleware"]
