"""HTTP client for posting webhooks back to kairos-gateway.

Phase 2A uses this to notify the gateway when a routing_policy_version is
activated (so the gateway's in-memory cache can invalidate the scope).

Errors are logged and swallowed in Phase 2A — webhook delivery is best-effort
since gateway pulls full policy state periodically as a fallback (per spec
§5.5 L3 variant flow). Phase 2B may upgrade to durable delivery via Inngest.
"""

from __future__ import annotations

import logging

import httpx

from kairos_evolve.core.envelope import sign_envelope
from kairos_evolve.core.time import Clock

log = logging.getLogger(__name__)


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


__all__ = ["GatewayEventsClient"]
