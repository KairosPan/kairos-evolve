"""Idempotency-Key middleware.

After envelope_verify has run (so request.state.body_obj is set), this
middleware resolves an idempotency key, then:
  - looks up the key in kairos_audit.idempotency_keys
  - if hit & request_hash matches: returns cached response with X-Idempotent-Replay: true
  - if hit & request_hash differs: returns 409
  - if miss: runs handler, stores response in idempotency table for replay TTL

Key resolution (spec D9):
  - if the caller supplied an ``Idempotency-Key`` header, use it;
  - else, if the verified body carries a ``job_id``, derive a deterministic
    body key ``jobs-run:{job_id}`` (the candidate-return producer signs the
    job body but never sends a client key — ``optimizer.client.envelope_signer
    .headers_from_envelope`` emits only the X-Envelope-* headers). This mirrors
    the OUTBOUND ``candidate:{job_id}`` key the producer uses for its own push;
  - else (a write with neither): reject 400, as before.

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

        # The verified body the envelope middleware stashed (it runs OUTSIDE this
        # one, so body_obj is already set for signed writes). Used both to derive
        # a fallback key and to compute the request hash.
        body_obj = getattr(request.state, "body_obj", None)

        key = request.headers.get("Idempotency-Key")
        if not key:
            # No client-supplied key: derive one from the body's correlation id
            # if present (spec D9 — the candidate-return producer signs the job
            # body but sends no Idempotency-Key). Otherwise reject the write.
            job_id = body_obj.get("job_id") if isinstance(body_obj, dict) else None
            if job_id is not None:
                key = f"jobs-run:{job_id}"
            else:
                return JSONResponse(
                    {"detail": "Idempotency-Key header required"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        # Compute request_hash from the verified body; if envelope middleware
        # didn't run (programmer error), fall back to raw body bytes.
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
