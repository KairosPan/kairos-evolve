"""Routing endpoints — events batch ingest + active policy retrieval."""

import uuid
from datetime import UTC, datetime

import pytest

from tests.api.conftest import make_envelope_headers


@pytest.mark.asyncio
async def test_post_events_batch_writes_rows(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    batch_id = str(uuid.uuid4())
    body = {
        "batch_id": batch_id,
        "merkle_root": "deadbeef" * 8,
        "events": [
            {
                "event_id": "ev-a",
                "scope_key": "skill:statute-compare",
                "query_hash": "qh-a",
                "routed_skill_id": "statute-compare",
                "accepted_skill_id": None,
                "at": datetime(2026, 5, 20, 12, 0, tzinfo=UTC).isoformat(),
            },
            {
                "event_id": "ev-b",
                "scope_key": "skill:statute-compare",
                "query_hash": "qh-b",
                "routed_skill_id": "statute-compare",
                "accepted_skill_id": "penalty-extract",
                "at": datetime(2026, 5, 20, 12, 1, tzinfo=UTC).isoformat(),
            },
        ],
    }
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    resp = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    assert resp.status_code == 202
    js = resp.json()
    assert js["inserted"] == 2
    assert js["batch_id"] == batch_id


@pytest.mark.asyncio
async def test_get_active_policy_returns_404_when_absent(asgi_client):
    resp = await asgi_client.get("/v1/routing/policies/skill:absent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_events_batch_replays_idempotently(asgi_client, gateway_keypair):
    """Same Idempotency-Key + same body → second call returns cached response."""
    priv, _ = gateway_keypair
    batch_id = str(uuid.uuid4())
    body = {
        "batch_id": batch_id,
        "merkle_root": "ab" * 32,
        "events": [],
    }
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    headers["Idempotency-Key"] = "ik-replay-test"
    first = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    second = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    assert first.json() == second.json()
    assert second.headers.get("X-Idempotent-Replay") == "true"


@pytest.mark.asyncio
async def test_events_batch_rejects_oversized(asgi_client, gateway_keypair, monkeypatch):
    """Reject batches larger than KAIROS_EVOLVE_ROUTING_EVENT_BATCH_MAX_SIZE."""
    priv, _ = gateway_keypair
    # Build a body with 2 events; we'll set the max-size limit to 1 via env var
    # before the request, but the fixture has already constructed the app —
    # so verify against the default (1000) by sending a way-too-big batch.
    too_many = [
        {
            "event_id": f"ev-big-{i}",
            "scope_key": "skill:x",
            "query_hash": f"qh-{i}",
            "routed_skill_id": "x",
            "accepted_skill_id": None,
            "at": "2026-05-20T12:00:00+00:00",
        }
        for i in range(1001)  # one over the default 1000
    ]
    batch_id = "00000000-0000-0000-0000-000000000777"
    body = {"batch_id": batch_id, "merkle_root": "x", "events": too_many}
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    headers["Idempotency-Key"] = "ik-oversized"
    resp = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    assert resp.status_code == 413
    assert "batch" in resp.text.lower()
