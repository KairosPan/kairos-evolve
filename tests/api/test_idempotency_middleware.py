"""Idempotency middleware tests."""

from __future__ import annotations

import pytest

from tests.api.conftest import make_envelope_headers


@pytest.mark.asyncio
async def test_first_request_processed(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    body = {"events": [], "batch_id": "00000000-0000-0000-0000-000000000001", "merkle_root": "x"}
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    headers["Idempotency-Key"] = "ik-first"
    resp = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    assert resp.status_code in (200, 202)


@pytest.mark.asyncio
async def test_replay_same_key_returns_cached(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    body = {"events": [], "batch_id": "00000000-0000-0000-0000-000000000002", "merkle_root": "x"}
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    headers["Idempotency-Key"] = "ik-replay"
    first = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    second = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    assert first.status_code == second.status_code
    assert first.json() == second.json()
    assert second.headers.get("X-Idempotent-Replay") == "true"


@pytest.mark.asyncio
async def test_collision_returns_409(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    body_a = {"events": [], "batch_id": "00000000-0000-0000-0000-000000000003", "merkle_root": "a"}
    headers_a = make_envelope_headers(
        body=body_a,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    headers_a["Idempotency-Key"] = "ik-collide"
    await asgi_client.post("/v1/routing/events/batch", json=body_a, headers=headers_a)

    body_b = {"events": [], "batch_id": "00000000-0000-0000-0000-000000000004", "merkle_root": "b"}
    headers_b = make_envelope_headers(
        body=body_b,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    headers_b["Idempotency-Key"] = "ik-collide"
    resp = await asgi_client.post("/v1/routing/events/batch", json=body_b, headers=headers_b)
    assert resp.status_code == 409
    assert "idempotency" in resp.text.lower()
