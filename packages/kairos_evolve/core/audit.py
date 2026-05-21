"""Audit log writer — single signed rows + batched envelope rows.

Per spec §3.7 signing strategy:
  - Low-frequency state-transition events (policy.activate, proposal.approved,
    selfmod.canary_promote, etc.) → `write_signed()` with per-row signature.
  - High-frequency events (routing.event, shadow.record.write) → `write_batch()`
    inserts one envelope_batches row (Merkle root + batch signature) plus N
    rows in audit_log whose `batch_id` references it; per-row signature is NULL.

`write_signed()` optionally chains rows via `prev_id` for tamper detection
across a session.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from kairos_evolve.core.time import Clock


@dataclass(frozen=True)
class AuditEntry:
    actor_service: str
    actor_key_id: str
    body_sha256: str
    target_schema: str
    target_table: str
    target_id: str
    action: str
    payload: dict[str, Any]
    request_id: str | None = None
    idempotency_key: str | None = None
    envelope_hash: str | None = None
    previous_state: str | None = None
    next_state: str | None = None


@dataclass(frozen=True)
class EnvelopeBatch:
    batch_id: uuid.UUID
    merkle_root: str
    member_count: int


class AuditWriter:
    """psycopg-backed audit log + envelope_batches writer."""

    def __init__(self, conn, *, clock: Clock, chain: bool = False):
        self._conn = conn
        self._clock = clock
        self._chain = chain
        self._last_id: uuid.UUID | None = None

    def write_signed(self, entry: AuditEntry, *, signature: bytes) -> uuid.UUID:
        """Insert a single signed audit row. Returns the new id."""
        new_id = uuid.uuid4()
        prev = self._last_id if self._chain else None
        self._insert_row(
            row_id=new_id,
            prev_id=prev,
            entry=entry,
            signature=signature,
            batch_id=None,
        )
        if self._chain:
            self._last_id = new_id
        self._conn.commit()
        return new_id

    def write_batch(
        self,
        *,
        entries: list[AuditEntry],
        merkle_root: str,
        batch_signature: bytes,
        signed_by: str,
        event_kinds: list[str],
    ) -> EnvelopeBatch:
        """Insert one envelope_batches row + N audit_log rows referencing it.

        Per-row signature is NULL; verification reduces to verifying the batch
        Merkle root against batch_signature.
        """
        batch_id = uuid.uuid4()
        now = self._clock.now()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kairos_audit.envelope_batches
                    (batch_id, event_kinds, merkle_root, member_count, signature, signed_by, ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (batch_id, event_kinds, merkle_root, len(entries), batch_signature, signed_by, now),
            )
            for entry in entries:
                row_id = uuid.uuid4()
                self._insert_row(
                    row_id=row_id,
                    prev_id=None,
                    entry=entry,
                    signature=None,
                    batch_id=batch_id,
                    cur=cur,
                )
        self._conn.commit()
        return EnvelopeBatch(batch_id=batch_id, merkle_root=merkle_root, member_count=len(entries))

    def _insert_row(
        self,
        *,
        row_id: uuid.UUID,
        prev_id: uuid.UUID | None,
        entry: AuditEntry,
        signature: bytes | None,
        batch_id: uuid.UUID | None,
        cur=None,
    ) -> None:
        sql = """
            INSERT INTO kairos_audit.audit_log (
                id, prev_id, actor_service, actor_key_id, request_id, idempotency_key,
                envelope_hash, body_sha256, target_schema, target_table, target_id,
                action, previous_state, next_state, signature, batch_id, payload, ts
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
            )
        """
        args = (
            row_id,
            prev_id,
            entry.actor_service,
            entry.actor_key_id,
            entry.request_id,
            entry.idempotency_key,
            entry.envelope_hash,
            entry.body_sha256,
            entry.target_schema,
            entry.target_table,
            entry.target_id,
            entry.action,
            entry.previous_state,
            entry.next_state,
            signature,
            batch_id,
            json.dumps(entry.payload),
            self._clock.now(),
        )
        if cur is None:
            with self._conn.cursor() as new_cur:
                new_cur.execute(sql, args)
        else:
            cur.execute(sql, args)


class AsyncAuditWriter:
    """Async psycopg sibling of ``AuditWriter``.

    Mirrors the sync surface (``write_signed`` / ``write_batch``) but
    operates on an ``AsyncConnection`` from ``psycopg_pool.AsyncConnectionPool``.
    The route handler in ``api/routes/routing.py`` uses the async pool;
    this class lets it replace inline SQL without giving up the sync
    helpers used by background workers and tests.

    Adds ``write_envelope_only`` for the high-frequency case where
    routing-event batches record an envelope row (idempotent on
    ``batch_id``) but skip per-event audit_log rows — the events
    themselves are the audit trail, indexed by ``batch_id``.
    """

    def __init__(self, aconn, *, clock: Clock, chain: bool = False):
        self._aconn = aconn
        self._clock = clock
        self._chain = chain
        self._last_id: uuid.UUID | None = None

    async def write_signed(self, entry: AuditEntry, *, signature: bytes) -> uuid.UUID:
        new_id = uuid.uuid4()
        prev = self._last_id if self._chain else None
        await self._insert_row(
            row_id=new_id,
            prev_id=prev,
            entry=entry,
            signature=signature,
            batch_id=None,
        )
        if self._chain:
            self._last_id = new_id
        await self._aconn.commit()
        return new_id

    async def write_batch(
        self,
        *,
        entries: list[AuditEntry],
        merkle_root: str,
        batch_signature: bytes,
        signed_by: str,
        event_kinds: list[str],
    ) -> EnvelopeBatch:
        batch_id = uuid.uuid4()
        now = self._clock.now()
        cur = self._aconn.cursor()
        try:
            await cur.execute(
                """
                INSERT INTO kairos_audit.envelope_batches
                    (batch_id, event_kinds, merkle_root, member_count, signature, signed_by, ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    batch_id,
                    event_kinds,
                    merkle_root,
                    len(entries),
                    batch_signature,
                    signed_by,
                    now,
                ),
            )
            for entry in entries:
                row_id = uuid.uuid4()
                await self._insert_row(
                    row_id=row_id,
                    prev_id=None,
                    entry=entry,
                    signature=None,
                    batch_id=batch_id,
                    cur=cur,
                )
        finally:
            await cur.close()
        await self._aconn.commit()
        return EnvelopeBatch(batch_id=batch_id, merkle_root=merkle_root, member_count=len(entries))

    async def write_envelope_only(
        self,
        *,
        batch_id: uuid.UUID,
        merkle_root: str,
        member_count: int,
        batch_signature: bytes,
        signed_by: str,
        event_kinds: list[str],
    ) -> None:
        """Insert just the envelope_batches row (no per-event audit_log rows).

        Used by high-frequency event ingest where the events themselves
        live in their own table (e.g. ``routing_events``) and the
        envelope is the only audit artefact. Idempotent on ``batch_id``
        so replays don't double-insert.
        """
        now = self._clock.now()
        cur = self._aconn.cursor()
        try:
            await cur.execute(
                """
                INSERT INTO kairos_audit.envelope_batches
                    (batch_id, event_kinds, merkle_root, member_count, signature, signed_by, ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (batch_id) DO NOTHING
                """,
                (
                    batch_id,
                    event_kinds,
                    merkle_root,
                    member_count,
                    batch_signature,
                    signed_by,
                    now,
                ),
            )
        finally:
            await cur.close()
        await self._aconn.commit()

    async def _insert_row(
        self,
        *,
        row_id: uuid.UUID,
        prev_id: uuid.UUID | None,
        entry: AuditEntry,
        signature: bytes | None,
        batch_id: uuid.UUID | None,
        cur=None,
    ) -> None:
        sql = """
            INSERT INTO kairos_audit.audit_log (
                id, prev_id, actor_service, actor_key_id, request_id, idempotency_key,
                envelope_hash, body_sha256, target_schema, target_table, target_id,
                action, previous_state, next_state, signature, batch_id, payload, ts
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
            )
        """
        args = (
            row_id,
            prev_id,
            entry.actor_service,
            entry.actor_key_id,
            entry.request_id,
            entry.idempotency_key,
            entry.envelope_hash,
            entry.body_sha256,
            entry.target_schema,
            entry.target_table,
            entry.target_id,
            entry.action,
            entry.previous_state,
            entry.next_state,
            signature,
            batch_id,
            json.dumps(entry.payload),
            self._clock.now(),
        )
        if cur is None:
            new_cur = self._aconn.cursor()
            try:
                await new_cur.execute(sql, args)
            finally:
                await new_cur.close()
        else:
            await cur.execute(sql, args)


__all__ = ["AsyncAuditWriter", "AuditEntry", "AuditWriter", "EnvelopeBatch"]
