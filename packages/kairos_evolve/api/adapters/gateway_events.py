"""HTTP client for posting webhooks back to kairos-gateway.

Phase 2A uses this to notify the gateway when a routing_policy_version is
activated (so the gateway's in-memory cache can invalidate the scope).

Errors are logged and swallowed for ``policy_invalidated`` in Phase 2A —
that webhook is best-effort since the gateway pulls full policy state
periodically as a fallback (per spec §5.5 L3 variant flow).

Slice 9 (#34) adds ``candidate_returned``: the candidate-return delivery is
NOT best-effort — its failure must surface so ``/v1/jobs/run`` can answer 5xx
and the caller's job retries (delivery durability via the job queue, spec D3).
So that method RETURNS the gateway's HTTP status (a returned non-2xx) and, on a
transport error (the gateway was never reached), returns ``TRANSPORT_ERROR_STATUS``
(a 5xx-class sentinel) instead of swallowing it — the route maps either to 502.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from kairos_evolve.core.candidate_contracts import CandidateReturn
from kairos_evolve.core.envelope import sign_envelope
from kairos_evolve.core.time import Clock

log = logging.getLogger(__name__)

# Sentinel status returned by ``candidate_returned`` when the outbound push
# never reached the gateway (transport error: ConnectError, timeout, ...). It is
# in the 5xx class so the route's ``status_code >= 400`` branch maps it to a 502
# (fail closed → the caller's job retries; spec D3), exactly like a returned 5xx.
TRANSPORT_ERROR_STATUS = 599


class GatewayEventsClient:
    def __init__(
        self,
        *,
        base_url: str,
        evolve_private_key,  # Ed25519PrivateKey
        evolve_key_id: str,
        clock: Clock,
        http: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._priv = evolve_private_key
        self._key_id = evolve_key_id
        self._clock = clock
        self._http = http or httpx.AsyncClient(timeout=5.0)

    async def policy_invalidated(self, *, scope_key: str, new_version: int) -> None:
        body = {"scope_key": scope_key, "new_version": new_version}
        env = sign_envelope(
            body=body,
            key=self._priv,
            key_id=self._key_id,
            service_id="kairos-evolve-api",
            ts=self._clock.now(),
        )
        headers = _envelope_headers(env)
        url = f"{self._base_url}/v1/webhooks/policy-invalidated"
        try:
            resp = await self._http.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                log.warning(
                    "policy-invalidated webhook returned %d for %s v%d: %s",
                    resp.status_code,
                    scope_key,
                    new_version,
                    resp.text,
                )
        except httpx.HTTPError as exc:
            log.warning(
                "policy-invalidated webhook delivery failed for %s v%d: %s",
                scope_key,
                new_version,
                exc,
            )

    async def candidate_returned(
        self,
        *,
        job_id: str,
        org_id: str,
        skill_id: str,
        candidate_text: str,
        evidence: dict[str, Any],
        spend_usd: float,
    ) -> int:
        """Sign a K_evolve ``CandidateReturn`` envelope + POST it to the intake.

        Returns the gateway webhook's HTTP status code so the caller can map a
        non-2xx to a 5xx (job retry). Unlike ``policy_invalidated`` this does NOT
        swallow delivery failures: a returned non-2xx is surfaced, and a transport
        error (ConnectError/timeout — the gateway was never reached) is caught and
        reported as ``TRANSPORT_ERROR_STATUS`` (a 5xx-class sentinel) rather than
        propagating as an unhandled 500. Either way the producer route fails closed
        so a candidate never silently vanishes (spec D3) — the difference from
        ``policy_invalidated`` is that here the failure is *reported*, not swallowed.

        ``job_id`` is the correlation key the intake replays on (D9). The body is
        D11-clean — only the candidate text + evidence + org binding, no matter.
        """
        body = CandidateReturn(
            job_id=job_id,
            org_id=org_id,
            skill_id=skill_id,
            candidate_text=candidate_text,
            evidence=evidence,
            spend_usd=spend_usd,
        ).model_dump(mode="json")
        env = sign_envelope(
            body=body,
            key=self._priv,
            key_id=self._key_id,
            service_id="kairos-evolve-api",
            ts=self._clock.now(),
        )
        headers = _envelope_headers(env)
        # The intake is itself idempotent on job_id; use it as the key so a
        # retried dispatch replays rather than double-delivers.
        headers["Idempotency-Key"] = f"candidate:{job_id}"
        url = f"{self._base_url}/v1/webhooks/jobs-finished"
        try:
            resp = await self._http.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            # The push never reached the gateway. Report a 5xx-class sentinel so
            # the route fails closed (502) instead of letting the error escape as
            # an unhandled 500 — same fail-closed outcome, but now mapped + logged.
            log.warning(
                "jobs-finished webhook delivery failed for job %s: %s",
                job_id,
                exc,
            )
            return TRANSPORT_ERROR_STATUS
        if resp.status_code >= 400:
            log.warning(
                "jobs-finished webhook returned %d for job %s: %s",
                resp.status_code,
                job_id,
                resp.text,
            )
        return resp.status_code

    async def aclose(self) -> None:
        await self._http.aclose()


def _envelope_headers(env) -> dict[str, str]:
    return {
        "X-Envelope-Version": env.version,
        "X-Envelope-Key-Id": env.key_id,
        "X-Envelope-Service-Id": env.service_id,
        "X-Envelope-Ts": env.ts.isoformat(),
        "X-Envelope-Nonce": env.nonce,
        "X-Envelope-Body-Sha256": env.body_sha256,
        "X-Envelope-Signature": env.signature,
        "Content-Type": "application/json",
    }


__all__ = ["TRANSPORT_ERROR_STATUS", "GatewayEventsClient"]
