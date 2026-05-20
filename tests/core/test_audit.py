"""Audit log writer tests against pytest-postgresql."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from kairos_evolve.core.audit import (
    AuditEntry,
    AuditWriter,
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


def test_write_single_signed_entry(evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    writer = AuditWriter(evolve_db, clock=clock)
    audit_id = writer.write_signed(_entry(), signature=b"\x01" * 64)
    assert isinstance(audit_id, uuid.UUID)

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT actor_service, action, signature IS NOT NULL, batch_id "
            "FROM kairos_audit.audit_log WHERE id = %s",
            (audit_id,),
        )
        row = cur.fetchone()
    assert row[0] == "kairos_evolve_api"
    assert row[1] == "routing.policy.activate"
    assert row[2] is True
    assert row[3] is None


def test_write_batched_entries_share_batch_id(evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    writer = AuditWriter(evolve_db, clock=clock)
    entries = [
        _entry(action="routing.event", target_id=f"ev-{i}", payload={"i": i}) for i in range(3)
    ]
    batch = writer.write_batch(
        entries=entries,
        merkle_root="merkle-root-hex",
        batch_signature=b"\x02" * 64,
        signed_by="K_gw",
        event_kinds=["routing.event"],
    )
    assert isinstance(batch, EnvelopeBatch)
    assert batch.member_count == 3

    with evolve_db.cursor() as cur:
        cur.execute(
            "SELECT batch_id, signature FROM kairos_audit.audit_log "
            "WHERE target_id LIKE 'ev-%' ORDER BY target_id"
        )
        rows = cur.fetchall()
    assert all(r[0] == batch.batch_id for r in rows)
    assert all(r[1] is None for r in rows)  # rows themselves unsigned


def test_audit_log_chain_links_prev_id(evolve_db):
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    writer = AuditWriter(evolve_db, clock=clock, chain=True)
    a1 = writer.write_signed(_entry(target_id="t1"), signature=b"\x01" * 64)
    a2 = writer.write_signed(_entry(target_id="t2"), signature=b"\x02" * 64)

    with evolve_db.cursor() as cur:
        cur.execute("SELECT prev_id FROM kairos_audit.audit_log WHERE id = %s", (a2,))
        prev = cur.fetchone()[0]
    assert prev == a1
