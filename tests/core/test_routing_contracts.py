"""Routing contracts — Pydantic round-trip + schema shape."""

from __future__ import annotations

from datetime import UTC, datetime

from kairos_evolve.core.routing_contracts import RoutingEvent, RoutingPolicy


def test_routing_event_roundtrip():
    ev = RoutingEvent(
        query="how do I file under §301?",
        routed_skill_id="statute-compare",
        accepted_skill_id=None,
        at=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
    )
    blob = ev.model_dump_json()
    back = RoutingEvent.model_validate_json(blob)
    assert back == ev


def test_routing_event_user_override():
    ev = RoutingEvent(
        query="extract penalty amount",
        routed_skill_id="statute-compare",
        accepted_skill_id="penalty-extract",
    )
    assert ev.accepted_skill_id == "penalty-extract"


def test_routing_policy_default_empty():
    p = RoutingPolicy()
    assert p.description_weights == {}
    assert p.trigger_hints == {}


def test_routing_policy_with_weights_roundtrip():
    p = RoutingPolicy(
        description_weights={"statute-compare": 1.4, "penalty-extract": 0.8},
        trigger_hints={"statute-compare": ["§", "section"]},
    )
    back = RoutingPolicy.model_validate_json(p.model_dump_json())
    assert back == p


def test_routing_event_json_schema_required_fields():
    schema = RoutingEvent.model_json_schema()
    required = set(schema["required"])
    assert {"query", "routed_skill_id"}.issubset(required)


def test_routing_policy_json_schema_dict_types():
    props = RoutingPolicy.model_json_schema()["properties"]
    assert props["description_weights"]["type"] == "object"
    assert props["trigger_hints"]["type"] == "object"


def test_evolve_db_fixture_applies_phase2a_ddl(evolve_db):
    """Smoke: pytest-postgresql + ddl_phase2a.sql produces the expected tables."""
    with evolve_db.cursor() as cur:
        cur.execute("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema IN ('kairos_evolve', 'kairos_audit')
            ORDER BY table_schema, table_name
        """)
        rows = cur.fetchall()
    names = {f"{s}.{t}" for s, t in rows}
    expected = {
        "kairos_audit.audit_log",
        "kairos_audit.envelope_batches",
        "kairos_audit.idempotency_keys",
        "kairos_evolve.routing_policies",
        "kairos_evolve.routing_policy_versions",
        "kairos_evolve.routing_events",
    }
    assert expected <= names, f"missing tables: {expected - names}"
