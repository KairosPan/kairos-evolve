"""envelope_verify middleware tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.api.conftest import make_envelope_headers


@pytest.mark.asyncio
async def test_unsigned_post_rejected_401(asgi_client):
    resp = await asgi_client.post("/v1/routing/events/batch", json={"events": []})
    assert resp.status_code == 401
    assert "envelope" in resp.text.lower()


@pytest.mark.asyncio
async def test_signed_post_with_correct_key_passes_middleware(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    body = {"events": [], "batch_id": "00000000-0000-0000-0000-000000000000", "merkle_root": "x"}
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    resp = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    assert resp.status_code in (200, 202, 422)


@pytest.mark.asyncio
async def test_signed_post_with_wrong_key_id_rejected(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    body = {"events": [], "batch_id": "00000000-0000-0000-0000-000000000000", "merkle_root": "x"}
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_unknown",
        service_id="kairos-gateway",
    )
    resp = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    assert resp.status_code == 401
    assert "unknown" in resp.text.lower() or "key_id" in resp.text.lower()


@pytest.mark.asyncio
async def test_tampered_body_rejected(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    body = {"events": [], "batch_id": "00000000-0000-0000-0000-000000000000", "merkle_root": "x"}
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    tampered = dict(body)
    tampered["merkle_root"] = "tampered"
    resp = await asgi_client.post("/v1/routing/events/batch", json=tampered, headers=headers)
    assert resp.status_code == 401
    assert "body_sha256" in resp.text.lower() or "envelope" in resp.text.lower()


@pytest.mark.asyncio
async def test_expired_envelope_rejected(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    body = {"events": [], "batch_id": "00000000-0000-0000-0000-000000000000", "merkle_root": "x"}
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
        ts=datetime.now(UTC) - timedelta(hours=1),
    )
    resp = await asgi_client.post("/v1/routing/events/batch", json=body, headers=headers)
    assert resp.status_code == 401
    assert "expired" in resp.text.lower()


@pytest.mark.asyncio
async def test_get_routes_bypass_envelope_verify(asgi_client):
    """Read-only GETs (health, active-policy) do not require an envelope."""
    resp = await asgi_client.get("/healthz")
    assert resp.status_code == 200
