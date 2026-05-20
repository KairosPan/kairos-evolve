"""Phase 2A jobs endpoint is a stub — accepts signed envelope, returns 202."""

import pytest

from tests.api.conftest import make_envelope_headers


@pytest.mark.asyncio
async def test_jobs_finished_returns_202_for_stub(asgi_client, gateway_keypair):
    priv, _ = gateway_keypair
    body = {"job_run_id": "jr-1", "status": "succeeded"}
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    headers["Idempotency-Key"] = "ik-job-stub"
    resp = await asgi_client.post("/v1/jobs/finished", json=body, headers=headers)
    assert resp.status_code == 202
    assert resp.json() == {"status": "accepted", "phase": "stub"}
