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
async def test_get_active_policy_returns_404_when_absent(asgi_client, gateway_keypair):
    # Phase 2A.x cleanup: GET /v1/routing/policies/* now requires the same
    # envelope auth as writes (it leaks routing weights). Bodyless signed
    # GET: envelope body is `{}`.
    priv, _ = gateway_keypair
    headers = make_envelope_headers(
        body={},
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    resp = await asgi_client.get("/v1/routing/policies/skill:absent", headers=headers)
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
async def test_get_active_policy_without_envelope_returns_401(asgi_client):
    # Phase 2A.x cleanup: unauthenticated reads of routing policy data
    # leak per-skill weights → 401 without an envelope.
    resp = await asgi_client.get("/v1/routing/policies/skill:absent")
    assert resp.status_code == 401
    assert "envelope" in resp.text.lower()


@pytest.mark.asyncio
async def test_get_active_policy_with_bad_envelope_returns_401(asgi_client, gateway_keypair):
    # Envelope present but signed with a different key (unknown key_id) → 401.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    rogue = Ed25519PrivateKey.generate()
    headers = make_envelope_headers(
        body={},
        private_key=rogue,
        key_id="K_rogue_not_registered",
        service_id="rogue-service",
    )
    resp = await asgi_client.get("/v1/routing/policies/skill:absent", headers=headers)
    assert resp.status_code == 401
    assert "unknown key_id" in resp.text


@pytest.mark.asyncio
async def test_events_batch_multi_scope_reports_all_versions(
    asgi_client, gateway_keypair, monkeypatch
):
    """A batch crossing two scopes that both bump policy must report BOTH
    new versions in `new_policy_versions`; `new_policy_version` (deprecated)
    stays `None` because a single integer can't honestly answer "the" new
    version when several were bumped.
    """
    # Force the bump threshold low so a small synthetic batch trips it.
    monkeypatch.setenv("KAIROS_EVOLVE_POLICY_BUMP_DELTA_THRESHOLD", "0.001")

    priv, _ = gateway_keypair
    batch_id = str(uuid.uuid4())
    # Two events in one scope, two events in another. Each scope has only
    # one routed_skill_id with no acceptance → Hebbian decrement; with the
    # threshold at 0.001 every scope bumps.
    body = {
        "batch_id": batch_id,
        "merkle_root": "cafe" * 16,
        "events": [
            {
                "event_id": "ev-multi-1",
                "scope_key": "skill:alpha",
                "query_hash": "qha-1",
                "routed_skill_id": "alpha",
                "accepted_skill_id": None,
                "at": datetime(2026, 5, 21, 10, 0, tzinfo=UTC).isoformat(),
            },
            {
                "event_id": "ev-multi-2",
                "scope_key": "skill:alpha",
                "query_hash": "qha-2",
                "routed_skill_id": "alpha",
                "accepted_skill_id": None,
                "at": datetime(2026, 5, 21, 10, 1, tzinfo=UTC).isoformat(),
            },
            {
                "event_id": "ev-multi-3",
                "scope_key": "skill:beta",
                "query_hash": "qhb-1",
                "routed_skill_id": "beta",
                "accepted_skill_id": None,
                "at": datetime(2026, 5, 21, 10, 2, tzinfo=UTC).isoformat(),
            },
            {
                "event_id": "ev-multi-4",
                "scope_key": "skill:beta",
                "query_hash": "qhb-2",
                "routed_skill_id": "beta",
                "accepted_skill_id": None,
                "at": datetime(2026, 5, 21, 10, 3, tzinfo=UTC).isoformat(),
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
    assert js["inserted"] == 4
    assert js["policy_bumped"] is True
    versions = js["new_policy_versions"]
    assert set(versions.keys()) == {"skill:alpha", "skill:beta"}
    assert all(isinstance(v, int) and v >= 1 for v in versions.values())
    # Deprecated single-version field stays None when multiple scopes bumped.
    assert js["new_policy_version"] is None


@pytest.mark.asyncio
async def test_events_batch_single_scope_keeps_legacy_field_populated(
    asgi_client, gateway_keypair, monkeypatch
):
    """Single-scope bump still populates the deprecated `new_policy_version`
    field for clients that haven't migrated to `new_policy_versions` yet.
    """
    monkeypatch.setenv("KAIROS_EVOLVE_POLICY_BUMP_DELTA_THRESHOLD", "0.001")
    priv, _ = gateway_keypair
    batch_id = str(uuid.uuid4())
    body = {
        "batch_id": batch_id,
        "merkle_root": "1234" * 16,
        "events": [
            {
                "event_id": "ev-solo-1",
                "scope_key": "skill:gamma",
                "query_hash": "qhg-1",
                "routed_skill_id": "gamma",
                "accepted_skill_id": None,
                "at": datetime(2026, 5, 21, 11, 0, tzinfo=UTC).isoformat(),
            },
            {
                "event_id": "ev-solo-2",
                "scope_key": "skill:gamma",
                "query_hash": "qhg-2",
                "routed_skill_id": "gamma",
                "accepted_skill_id": None,
                "at": datetime(2026, 5, 21, 11, 1, tzinfo=UTC).isoformat(),
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
    assert js["policy_bumped"] is True
    assert list(js["new_policy_versions"].keys()) == ["skill:gamma"]
    one_version = js["new_policy_versions"]["skill:gamma"]
    # Back-compat: legacy field equals the single dict entry.
    assert js["new_policy_version"] == one_version


@pytest.mark.asyncio
async def test_events_batch_no_bump_returns_empty_versions_dict(
    asgi_client, gateway_keypair, monkeypatch
):
    # Threshold high enough that no bump fires → empty dict + None legacy
    # field. Confirms `new_policy_versions` defaults to {} on the wire so
    # clients can iterate it unconditionally.
    monkeypatch.setenv("KAIROS_EVOLVE_POLICY_BUMP_DELTA_THRESHOLD", "1.0")
    priv, _ = gateway_keypair
    batch_id = str(uuid.uuid4())
    body = {
        "batch_id": batch_id,
        "merkle_root": "0011" * 16,
        "events": [
            {
                "event_id": "ev-quiet-1",
                "scope_key": "skill:delta",
                "query_hash": "qhd-1",
                "routed_skill_id": "delta",
                "accepted_skill_id": None,
                "at": datetime(2026, 5, 21, 12, 0, tzinfo=UTC).isoformat(),
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
    assert js["policy_bumped"] is False
    assert js["new_policy_versions"] == {}
    assert js["new_policy_version"] is None


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
