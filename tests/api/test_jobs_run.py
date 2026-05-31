"""POST /v1/jobs/run — Slice 9 (#34) candidate-return producer.

Verifies the gateway-signed job body (middleware), runs the FAKE evolve compute
synchronously, signs a K_evolve candidate+evidence envelope, and POSTs it to the
gateway ``/v1/webhooks/jobs-finished`` intake.

Outbound delivery is mocked at the httpx transport layer (no respx/pytest-httpx
in the env) so the test can both (a) assert the K_evolve-signed candidate body +
headers actually went out and (b) simulate a push failure to prove durability:
a non-2xx from the gateway webhook surfaces as a 5xx from ``/v1/jobs/run`` so the
caller's job backs off + retries (spec D3).
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kairos_evolve.core.candidate_contracts import CandidateReturn
from kairos_evolve.core.envelope import EnvelopeV1, verify_envelope

from tests.api.conftest import make_envelope_headers, make_envelope_headers_no_idempotency


def _job_body() -> dict:
    """A D11-clean job-run body (mirrors kairos RemoteEvolveExecutor / post_job_run)."""
    return {
        "job_id": "job-abc-123",
        "org_id": "org-acme",
        "kind": "skill_body",
        "target_ref": "statute-compare",
        "target_base_version": "0.1.0",
    }


class _RecordingTransport(httpx.MockTransport):
    """Captures the single outbound candidate POST and returns a chosen status."""

    def __init__(self, *, status_code: int):
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(status_code, json={"status": "accepted"})

        super().__init__(handler)


class _RaisingTransport(httpx.MockTransport):
    """Records the attempted outbound POST then raises a transport error.

    Models a real ConnectError / read timeout on the candidate push (the gateway
    is unreachable), which is distinct from the gateway returning a non-2xx.
    """

    def __init__(self, *, exc: httpx.HTTPError):
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            raise exc

        super().__init__(handler)


def _install_raising_outbound_mock(
    client: httpx.AsyncClient, *, exc: httpx.HTTPError
) -> _RaisingTransport:
    """Swap gateway_events' httpx transport for one that raises a transport error."""
    app = client._transport.app  # type: ignore[attr-defined]
    transport = _RaisingTransport(exc=exc)
    app.state.gateway_events._http = httpx.AsyncClient(transport=transport, timeout=5.0)
    return transport


def _install_outbound_mock(client: httpx.AsyncClient, *, status_code: int) -> _RecordingTransport:
    """Swap the gateway_events client's httpx transport for a recording mock.

    ``client`` is the ASGI test client; the FastAPI app hangs off its transport.
    """
    app = client._transport.app  # type: ignore[attr-defined]
    transport = _RecordingTransport(status_code=status_code)
    app.state.gateway_events._http = httpx.AsyncClient(transport=transport, timeout=5.0)
    return transport


@pytest.mark.asyncio
async def test_jobs_run_verifies_runs_fake_compute_and_returns_signed_candidate(
    asgi_client, gateway_keypair
):
    priv, _ = gateway_keypair
    outbound = _install_outbound_mock(asgi_client, status_code=200)

    body = _job_body()
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    resp = await asgi_client.post("/v1/jobs/run", json=body, headers=headers)

    assert resp.status_code == 202, resp.text
    js = resp.json()
    assert js["job_id"] == "job-abc-123"

    # Exactly one candidate POST went to the gateway webhook.
    assert len(outbound.requests) == 1
    req = outbound.requests[0]
    assert req.url.path.endswith("/v1/webhooks/jobs-finished")

    # The candidate body matches the locked CandidateReturn wire shape and
    # carries the originating job_id + org binding (D8/D9) — and NO matter.
    sent = json.loads(req.content.decode("utf-8"))
    candidate = CandidateReturn.model_validate(sent)
    assert candidate.job_id == "job-abc-123"
    assert candidate.org_id == "org-acme"
    assert candidate.skill_id == "statute-compare"
    assert candidate.candidate_text  # fake rewriter produced something
    assert candidate.spend_usd >= 0.0
    assert isinstance(candidate.evidence, dict)

    # The candidate envelope is K_evolve-signed and verifies against the evolve
    # public key over the exact body that was sent (no new crypto — reuse verify).
    envelope = EnvelopeV1(
        version=req.headers["x-envelope-version"],
        key_id=req.headers["x-envelope-key-id"],
        service_id=req.headers["x-envelope-service-id"],
        ts=datetime.fromisoformat(req.headers["x-envelope-ts"]),
        nonce=req.headers["x-envelope-nonce"],
        body_sha256=req.headers["x-envelope-body-sha256"],
        signature=req.headers["x-envelope-signature"],
    )
    assert envelope.key_id == "K_evolve_test"
    # Re-derive the evolve public key from the known test private key (33*32) and
    # verify the candidate envelope against the exact body sent (reuse verify).
    evolve_priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("33" * 32))
    verify_envelope(envelope, body=sent, public_key=evolve_priv.public_key())


@pytest.mark.asyncio
async def test_jobs_run_push_failure_surfaces_as_5xx(asgi_client, gateway_keypair):
    """A non-2xx from the gateway webhook → 5xx from /v1/jobs/run (job retries)."""
    priv, _ = gateway_keypair
    outbound = _install_outbound_mock(asgi_client, status_code=500)

    body = _job_body()
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    resp = await asgi_client.post("/v1/jobs/run", json=body, headers=headers)

    assert resp.status_code >= 500, resp.text
    # The candidate push WAS attempted (so the failure is a delivery failure,
    # not a compute failure) — the caller's job will retry the whole dispatch.
    assert len(outbound.requests) == 1


@pytest.mark.asyncio
async def test_jobs_run_accepts_production_headers_without_idempotency_key(
    asgi_client, gateway_keypair
):
    """The real caller (RemoteEvolveExecutor → headers_from_envelope) sends ONLY the
    seven X-Envelope-* headers and NO Idempotency-Key. The route must derive its
    idempotency key from the verified body's ``job_id`` (spec D9) and answer 202 —
    otherwise IdempotencyMiddleware 400s every production dispatch forever."""
    priv, _ = gateway_keypair
    outbound = _install_outbound_mock(asgi_client, status_code=200)

    body = _job_body()
    # Headers EXACTLY as the production caller's headers_from_envelope produces —
    # no Idempotency-Key (the kairos signer never adds one for /v1/jobs/run).
    headers = make_envelope_headers_no_idempotency(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    assert "Idempotency-Key" not in headers  # guard: matches the real wire exactly

    resp = await asgi_client.post("/v1/jobs/run", json=body, headers=headers)

    assert resp.status_code == 202, resp.text
    assert resp.json()["job_id"] == "job-abc-123"
    # The body-derived idempotency key still let the candidate push through.
    assert len(outbound.requests) == 1


@pytest.mark.asyncio
async def test_jobs_run_transport_error_surfaces_as_5xx(asgi_client, gateway_keypair):
    """A transport error (ConnectError/timeout) on the candidate push → 5xx from
    /v1/jobs/run (the caller's job retries; spec D3) AND the push WAS attempted —
    proving the failure is a delivery failure, not a silent drop."""
    priv, _ = gateway_keypair
    outbound = _install_raising_outbound_mock(
        asgi_client, exc=httpx.ConnectError("gateway unreachable")
    )

    body = _job_body()
    headers = make_envelope_headers(
        body=body,
        private_key=priv,
        key_id="K_gw_test",
        service_id="kairos-gateway",
    )
    resp = await asgi_client.post("/v1/jobs/run", json=body, headers=headers)

    assert resp.status_code >= 500, resp.text
    assert len(outbound.requests) == 1


@pytest.mark.asyncio
async def test_jobs_run_rejects_unsigned_request(asgi_client):
    """No envelope → 401 from EnvelopeVerifyMiddleware (no per-route auth code)."""
    resp = await asgi_client.post("/v1/jobs/run", json=_job_body())
    assert resp.status_code == 401
