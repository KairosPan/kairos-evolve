"""Async sibling tests for AsyncRoutingStore + free-function async helpers."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import psycopg
import pytest
import pytest_asyncio
from kairos_evolve.core.audit import AsyncAuditWriter, AuditEntry
from kairos_evolve.core.routing_store import (
    AsyncRoutingStore,
    RoutingEventRow,
    async_activate_policy_version,
    async_record_routing_events,
)
from kairos_evolve.core.time import FakeClock


@pytest_asyncio.fixture
async def aconn(evolve_db) -> AsyncIterator[psycopg.AsyncConnection]:
    info = evolve_db.info
    conninfo = f"host={info.host} port={info.port} dbname={info.dbname} user={info.user}"
    conn = await psycopg.AsyncConnection.connect(conninfo)
    try:
        yield conn
    finally:
        await conn.close()


def _audit_entry(scope_key: str) -> AuditEntry:
    return AuditEntry(
        actor_service="kairos_evolve_api",
        actor_key_id="K_evolve",
        body_sha256="policy-bump",
        target_schema="kairos_evolve",
        target_table="routing_policy_versions",
        target_id=scope_key,
        action="routing.policy.activate",
        payload={"scope_key": scope_key},
        previous_state="staged",
        next_state="active",
    )


# ---------------------------------------------------------------------------
# async_record_routing_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_record_routing_events_dedupes_on_event_id(aconn, evolve_db):
    clock = FakeClock(datetime(2026, 5, 21, tzinfo=UTC))
    audit = AsyncAuditWriter(aconn, clock=clock)
    batch_id = uuid.uuid4()
    await audit.write_envelope_only(
        batch_id=batch_id,
        merkle_root="ab" * 32,
        member_count=2,
        batch_signature=b"\x00" * 64,
        signed_by="K_gw",
        event_kinds=["routing.event"],
    )

    events = [
        RoutingEventRow(
            event_id="ev-a",
            scope_key="skill:test",
            query_hash="qh-a",
            routed_skill_id="x",
            accepted_skill_id=None,
            at=datetime(2026, 5, 21, tzinfo=UTC),
        ),
        RoutingEventRow(
            event_id="ev-b",
            scope_key="skill:test",
            query_hash="qh-b",
            routed_skill_id="x",
            accepted_skill_id="y",
            at=datetime(2026, 5, 21, tzinfo=UTC),
        ),
    ]
    first_n = await async_record_routing_events(aconn, events, batch_id=batch_id)
    second_n = await async_record_routing_events(aconn, events, batch_id=batch_id)

    assert first_n == 2
    assert second_n == 0  # dedup on event_id

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM kairos_evolve.routing_events WHERE batch_id = %s",
            (batch_id,),
        )
        assert cur.fetchone()[0] == 2


@pytest.mark.asyncio
async def test_async_record_routing_events_empty_list_returns_zero(aconn):
    assert await async_record_routing_events(aconn, [], batch_id=uuid.uuid4()) == 0


# ---------------------------------------------------------------------------
# AsyncRoutingStore.insert_policy_version + async_activate_policy_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_policy_version_then_activate(aconn, evolve_db):
    clock = FakeClock(datetime(2026, 5, 21, 12, 0, tzinfo=UTC))
    audit = AsyncAuditWriter(aconn, clock=clock)
    store = AsyncRoutingStore(aconn, clock=clock)

    audit_id = await audit.write_signed(_audit_entry("skill:alpha"), signature=b"\x01" * 64)

    v1 = await store.insert_policy_version(
        scope_key="skill:alpha",
        description_weights={"alpha": 1.5},
        trigger_hints={"alpha": ["test"]},
        signed_by="K_evolve",
        signature=b"\x02" * 64,
        audit_id=audit_id,
    )
    assert v1 == 1
    # Pre-activation: get_active_policy returns None (activated_at is NULL).
    assert await store.get_active_policy("skill:alpha") is None

    await async_activate_policy_version(
        aconn, scope_key="skill:alpha", policy_version=v1, clock=clock
    )
    active = await store.get_active_policy("skill:alpha")
    assert active is not None
    assert active.policy_version == 1
    assert active.description_weights == {"alpha": 1.5}


@pytest.mark.asyncio
async def test_insert_policy_version_increments_per_scope(aconn):
    clock = FakeClock(datetime(2026, 5, 21, tzinfo=UTC))
    audit = AsyncAuditWriter(aconn, clock=clock)
    store = AsyncRoutingStore(aconn, clock=clock)

    for i in range(1, 4):
        aid = await audit.write_signed(_audit_entry("skill:beta"), signature=b"\x00" * 64)
        v = await store.insert_policy_version(
            scope_key="skill:beta",
            description_weights={"beta": float(i)},
            trigger_hints={},
            signed_by="K_evolve",
            signature=b"\x00" * 64,
            audit_id=aid,
        )
        assert v == i


@pytest.mark.asyncio
async def test_activate_supersedes_previous_active(aconn, evolve_db):
    clock = FakeClock(datetime(2026, 5, 21, tzinfo=UTC))
    audit = AsyncAuditWriter(aconn, clock=clock)
    store = AsyncRoutingStore(aconn, clock=clock)

    # Insert + activate v1.
    aid1 = await audit.write_signed(_audit_entry("skill:gamma"), signature=b"\x00" * 64)
    v1 = await store.insert_policy_version(
        scope_key="skill:gamma",
        description_weights={"gamma": 1.0},
        trigger_hints={},
        signed_by="K",
        signature=b"\x00" * 64,
        audit_id=aid1,
    )
    await async_activate_policy_version(
        aconn, scope_key="skill:gamma", policy_version=v1, clock=clock
    )

    # Insert + activate v2 — should supersede v1.
    aid2 = await audit.write_signed(_audit_entry("skill:gamma"), signature=b"\x00" * 64)
    v2 = await store.insert_policy_version(
        scope_key="skill:gamma",
        description_weights={"gamma": 2.0},
        trigger_hints={},
        signed_by="K",
        signature=b"\x00" * 64,
        audit_id=aid2,
    )
    await async_activate_policy_version(
        aconn, scope_key="skill:gamma", policy_version=v2, clock=clock
    )

    active = await store.get_active_policy("skill:gamma")
    assert active.policy_version == 2

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT policy_version, activated_at IS NOT NULL, superseded_at IS NOT NULL "
            "FROM kairos_evolve.routing_policy_versions "
            "WHERE scope_key = 'skill:gamma' ORDER BY policy_version"
        )
        rows = cur.fetchall()
    # v1 → superseded; v2 → active.
    assert rows[0] == (1, True, True)
    assert rows[1] == (2, True, False)


@pytest.mark.asyncio
async def test_get_active_policy_missing_scope_returns_none(aconn):
    clock = FakeClock(datetime(2026, 5, 21, tzinfo=UTC))
    store = AsyncRoutingStore(aconn, clock=clock)
    assert await store.get_active_policy("skill:not-real") is None
