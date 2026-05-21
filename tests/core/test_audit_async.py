"""Async sibling tests for AsyncAuditWriter — parity with test_audit.py.

The sync `AuditWriter` is already exercised in `test_audit.py`. This file
re-runs the same surface against `AsyncAuditWriter` to lock the contract
parity and the additional `write_envelope_only` method.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import psycopg
import pytest
import pytest_asyncio
from kairos_evolve.core.audit import (
    AsyncAuditWriter,
    AuditEntry,
    EnvelopeBatch,
)
from kairos_evolve.core.time import FakeClock


def _entry(**overrides) -> AuditEntry:
    base = dict(
        actor_service="kairos_evolve_api",
        actor_key_id="K_evolve",
        request_id="req-1",
        idempotency_key="ik-1",
        envelope_hash="env-sha-deadbeef",
        body_sha256="body-sha-cafe",
        target_schema="kairos_evolve",
        target_table="routing_policy_versions",
        target_id="rp-1",
        action="routing.policy.activate",
        previous_state="staged",
        next_state="active",
        payload={"scope_key": "skill:statute-compare", "policy_version": 1},
    )
    base.update(overrides)
    return AuditEntry(**base)


@pytest_asyncio.fixture
async def aconn(evolve_db) -> AsyncIterator[psycopg.AsyncConnection]:
    """Async psycopg connection bound to the same test DB as `evolve_db`.

    `evolve_db` is a sync psycopg connection; we re-open the same db
    asynchronously so the async helpers can exercise the schema the
    sync fixture set up.
    """
    info = evolve_db.info
    conninfo = f"host={info.host} port={info.port} dbname={info.dbname} user={info.user}"
    conn = await psycopg.AsyncConnection.connect(conninfo)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_async_write_signed_inserts_row(aconn, evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    writer = AsyncAuditWriter(aconn, clock=clock)

    audit_id = await writer.write_signed(_entry(), signature=b"\x01" * 64)
    assert isinstance(audit_id, uuid.UUID)

    # Verify via the sync connection.
    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT actor_service, action, signature IS NOT NULL, batch_id "
            "FROM kairos_audit.audit_log WHERE id = %s",
            (audit_id,),
        )
        row = cur.fetchone()
    assert row[0] == "kairos_evolve_api"
    assert row[1] == "routing.policy.activate"
    assert row[2] is True  # signature populated
    assert row[3] is None  # no batch


@pytest.mark.asyncio
async def test_async_write_batch_envelope_plus_audit_rows(aconn, evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    writer = AsyncAuditWriter(aconn, clock=clock)
    entries = [_entry(target_id=f"rp-{i}") for i in range(3)]

    batch = await writer.write_batch(
        entries=entries,
        merkle_root="cafe" * 16,
        batch_signature=b"\x02" * 64,
        signed_by="K_gw",
        event_kinds=["routing.event"],
    )
    assert isinstance(batch, EnvelopeBatch)
    assert batch.member_count == 3

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT member_count FROM kairos_audit.envelope_batches WHERE batch_id = %s",
            (batch.batch_id,),
        )
        row = cur.fetchone()
        assert row[0] == 3

        cur.execute(
            "SELECT COUNT(*) FROM kairos_audit.audit_log WHERE batch_id = %s",
            (batch.batch_id,),
        )
        n = cur.fetchone()[0]
        assert n == 3


@pytest.mark.asyncio
async def test_async_write_envelope_only_inserts_envelope_no_audit_rows(aconn, evolve_db):
    """High-frequency routing events use this: envelope row only, no per-event
    audit_log rows (the events themselves live in routing_events)."""
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    writer = AsyncAuditWriter(aconn, clock=clock)
    batch_id = uuid.uuid4()

    await writer.write_envelope_only(
        batch_id=batch_id,
        merkle_root="deadbeef" * 8,
        member_count=42,
        batch_signature=b"\x03" * 64,
        signed_by="K_gw",
        event_kinds=["routing.event"],
    )

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT member_count, signed_by FROM kairos_audit.envelope_batches WHERE batch_id = %s",
            (batch_id,),
        )
        row = cur.fetchone()
        assert row[0] == 42
        assert row[1] == "K_gw"

        cur.execute(
            "SELECT COUNT(*) FROM kairos_audit.audit_log WHERE batch_id = %s",
            (batch_id,),
        )
        # No per-event audit rows for this envelope.
        assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_async_write_envelope_only_is_idempotent(aconn, evolve_db):
    """ON CONFLICT (batch_id) DO NOTHING — replays don't duplicate."""
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    writer = AsyncAuditWriter(aconn, clock=clock)
    batch_id = uuid.uuid4()

    for _ in range(3):
        await writer.write_envelope_only(
            batch_id=batch_id,
            merkle_root="dead" * 16,
            member_count=10,
            batch_signature=b"\x04" * 64,
            signed_by="K_gw",
            event_kinds=["routing.event"],
        )

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM kairos_audit.envelope_batches WHERE batch_id = %s",
            (batch_id,),
        )
        assert cur.fetchone()[0] == 1


@pytest.mark.asyncio
async def test_async_chain_links_consecutive_signed_writes(aconn, evolve_db):
    """When `chain=True`, each signed row's prev_id points at the previous one."""
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    writer = AsyncAuditWriter(aconn, clock=clock, chain=True)

    first = await writer.write_signed(_entry(), signature=b"\x05" * 64)
    second = await writer.write_signed(_entry(), signature=b"\x06" * 64)
    third = await writer.write_signed(_entry(), signature=b"\x07" * 64)

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT id, prev_id FROM kairos_audit.audit_log WHERE id IN (%s, %s, %s) ORDER BY ts",
            (first, second, third),
        )
        rows = cur.fetchall()
    assert rows[0][1] is None  # first row has no prev
    assert rows[1][1] == first
    assert rows[2][1] == second
