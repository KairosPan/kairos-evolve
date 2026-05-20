"""Idempotency-Key storage + replay-detection backed by Postgres.

Every cross-service POST carries an `Idempotency-Key` header. On repeat:
  - same key + same request_hash → return the cached response.
  - same key + different request_hash → raise IdempotencyCollision (caller
    should 409 the client + audit `idempotency.collision`).

Expired entries (TTL) are treated as if absent. Cleanup runs separately via a
scheduled job — this module does not delete on its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from kairos_evolve.core.time import Clock


class IdempotencyCollision(Exception):
    """Same key, different request hash — caller must 409."""


@dataclass(frozen=True)
class IdempotencyHit:
    request_hash: str
    response_status: int
    response_body: Any | None


class IdempotencyStore:
    """psycopg-backed key/value store with TTL semantics."""

    def __init__(self, conn, *, clock: Clock):
        self._conn = conn
        self._clock = clock

    def get(self, key: str) -> IdempotencyHit | None:
        """Return the hit if present AND not expired, else None."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT request_hash, response_status, response_body_jsonb, expires_at
                  FROM kairos_audit.idempotency_keys
                 WHERE key = %s
                """,
                (key,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        request_hash, response_status, response_body, expires_at = row
        if self._clock.now() >= expires_at:
            return None
        return IdempotencyHit(
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
        )

    def put(
        self,
        *,
        key: str,
        request_hash: str,
        response_status: int,
        response_body: Any | None,
        ttl: timedelta,
    ) -> None:
        """Insert a new idempotency record (no upsert; collisions hit get)."""
        expires_at = self._clock.now() + ttl
        body_json = json.dumps(response_body) if response_body is not None else None
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kairos_audit.idempotency_keys
                    (key, request_hash, response_status, response_body_jsonb, created_at, expires_at)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (key) DO NOTHING
                """,
                (key, request_hash, response_status, body_json, self._clock.now(), expires_at),
            )
        self._conn.commit()

    def replay_if_present(self, *, key: str, request_hash: str) -> IdempotencyHit | None:
        """Lookup by key. If found and hash matches, return hit. If hash
        differs, raise IdempotencyCollision. If absent (or expired), None."""
        hit = self.get(key)
        if hit is None:
            return None
        if hit.request_hash != request_hash:
            raise IdempotencyCollision(
                f"key={key!r} replay with different request_hash: "
                f"stored={hit.request_hash[:8]}... new={request_hash[:8]}..."
            )
        return hit


__all__ = ["IdempotencyCollision", "IdempotencyHit", "IdempotencyStore"]
