"""routing_store tests — event ingest + active-policy retrieval."""

from __future__ import annotations

import datetime as _dt
import uuid

from kairos_evolve.core.audit import AuditEntry, AuditWriter
from kairos_evolve.core.routing_store import (
    ActivePolicy,
    RoutingEventRow,
    RoutingStore,
    activate_policy_version,
    record_routing_events,
)
from kairos_evolve.core.time import FakeClock


def _audit_id_for_fk(evolve_db, clock) -> uuid.UUID:
    """Helper: insert a row to grab a real id we can FK against in tests."""
    writer = AuditWriter(evolve_db, clock=clock)
    return writer.write_signed(
        AuditEntry(
            actor_service="kairos_evolve_api",
            actor_key_id="K_evolve",
            body_sha256="x",
            target_schema="kairos_evolve",
            target_table="routing_policy_versions",
            target_id="prepare-fk",
            action="prepare",
            payload={},
        ),
        signature=b"\x00" * 64,
    )


def test_record_routing_events_inserts_with_batch_id(evolve_db):
    clock = FakeClock(_dt.datetime(2026, 5, 20, tzinfo=_dt.UTC))
    writer = AuditWriter(evolve_db, clock=clock)
    batch = writer.write_batch(
        entries=[],  # no audit rows yet, just the batch
        merkle_root="m",
        batch_signature=b"\x01" * 64,
        signed_by="K_gw",
        event_kinds=["routing.event"],
    )
    events = [
        RoutingEventRow(
            event_id="ev-1",
            scope_key="skill:statute-compare:us:criminal",
            query_hash="qh-1",
            routed_skill_id="statute-compare",
            accepted_skill_id=None,
            at=_dt.datetime(2026, 5, 20, 12, 0, tzinfo=_dt.UTC),
        ),
        RoutingEventRow(
            event_id="ev-2",
            scope_key="skill:statute-compare:us:criminal",
            query_hash="qh-2",
            routed_skill_id="statute-compare",
            accepted_skill_id="penalty-extract",
            at=_dt.datetime(2026, 5, 20, 12, 1, tzinfo=_dt.UTC),
        ),
    ]
    inserted = record_routing_events(evolve_db, events, batch_id=batch.batch_id)
    assert inserted == 2

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT event_id, batch_id FROM kairos_evolve.routing_events "
            "WHERE batch_id = %s ORDER BY event_id",
            (batch.batch_id,),
        )
        rows = cur.fetchall()
    assert [r[0] for r in rows] == ["ev-1", "ev-2"]


def test_record_routing_events_event_id_dedupes(evolve_db):
    clock = FakeClock(_dt.datetime(2026, 5, 20, tzinfo=_dt.UTC))
    writer = AuditWriter(evolve_db, clock=clock)
    batch = writer.write_batch(
        entries=[],
        merkle_root="m",
        batch_signature=b"\x01" * 64,
        signed_by="K_gw",
        event_kinds=["routing.event"],
    )
    ev = RoutingEventRow(
        event_id="ev-dup",
        scope_key="skill:x",
        query_hash="qh",
        routed_skill_id="x",
        accepted_skill_id=None,
        at=_dt.datetime(2026, 5, 20, tzinfo=_dt.UTC),
    )
    record_routing_events(evolve_db, [ev], batch_id=batch.batch_id)
    inserted = record_routing_events(evolve_db, [ev], batch_id=batch.batch_id)
    assert inserted == 0


def test_activate_policy_version_marks_active_and_supersedes_prior(evolve_db):
    clock = FakeClock(_dt.datetime(2026, 5, 20, tzinfo=_dt.UTC))
    audit_a = _audit_id_for_fk(evolve_db, clock)
    audit_b = _audit_id_for_fk(evolve_db, clock)
    store = RoutingStore(evolve_db, clock=clock)

    v1 = store.insert_policy_version(
        scope_key="skill:x",
        description_weights={"a": 1.4},
        trigger_hints={"a": ["x"]},
        signed_by="K_evolve",
        signature=b"\x01" * 64,
        audit_id=audit_a,
    )
    activate_policy_version(evolve_db, scope_key="skill:x", policy_version=v1, clock=clock)
    active = store.get_active_policy("skill:x")
    assert isinstance(active, ActivePolicy)
    assert active.policy_version == v1
    assert active.description_weights == {"a": 1.4}

    v2 = store.insert_policy_version(
        scope_key="skill:x",
        description_weights={"a": 1.6, "b": 0.7},
        trigger_hints={},
        signed_by="K_evolve",
        signature=b"\x02" * 64,
        audit_id=audit_b,
    )
    clock.tick(_dt.timedelta(seconds=1))
    activate_policy_version(evolve_db, scope_key="skill:x", policy_version=v2, clock=clock)

    active = store.get_active_policy("skill:x")
    assert active.policy_version == v2

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT superseded_at IS NOT NULL "
            "FROM kairos_evolve.routing_policy_versions "
            "WHERE scope_key = 'skill:x' AND policy_version = %s",
            (v1,),
        )
        assert cur.fetchone()[0] is True


def test_get_active_policy_returns_none_when_empty(evolve_db):
    clock = FakeClock(_dt.datetime(2026, 5, 20, tzinfo=_dt.UTC))
    store = RoutingStore(evolve_db, clock=clock)
    assert store.get_active_policy("nope") is None
