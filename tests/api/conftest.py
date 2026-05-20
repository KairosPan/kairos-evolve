"""Shared API test fixtures: FastAPI app + signed envelope helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kairos_evolve.core.envelope import sign_envelope


@pytest.fixture
def gateway_keypair():
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


@pytest.fixture
def gateway_public_key_hex(gateway_keypair):
    _, pub = gateway_keypair
    raw = pub.public_bytes_raw()
    return raw.hex()


def make_envelope_headers(
    *,
    body: dict,
    private_key: Ed25519PrivateKey,
    key_id: str,
    service_id: str,
    ts: datetime | None = None,
) -> dict[str, str]:
    """Build X-Envelope-* + Idempotency-Key headers for a signed POST."""
    env = sign_envelope(
        body=body,
        key=private_key,
        key_id=key_id,
        service_id=service_id,
        ts=ts or datetime.now(UTC),
    )
    return {
        "X-Envelope-Version": env.version,
        "X-Envelope-Key-Id": env.key_id,
        "X-Envelope-Service-Id": env.service_id,
        "X-Envelope-Ts": env.ts.isoformat(),
        "X-Envelope-Nonce": env.nonce,
        "X-Envelope-Body-Sha256": env.body_sha256,
        "X-Envelope-Signature": env.signature,
        "Idempotency-Key": env.nonce,  # nonce doubles as idempotency in tests
        "Content-Type": "application/json",
    }


@pytest_asyncio.fixture
async def asgi_client(
    evolve_db,
    monkeypatch,
    gateway_public_key_hex,
) -> AsyncIterator[httpx.AsyncClient]:
    """Real FastAPI app exercised via httpx.AsyncClient + ASGI transport.

    Wires the evolve_db fixture as the Neon URL. Stubs the evolve key. Uses
    the test gateway public key for envelope verification.
    """
    from kairos_evolve.api.app import build_app

    # Use pytest-postgresql's actual conninfo
    info = evolve_db.info
    pg_url = f"postgresql://{info.user}@{info.host}:{info.port}/{info.dbname}"

    monkeypatch.setenv("KAIROS_EVOLVE_NEON_URL", pg_url)
    monkeypatch.setenv("KAIROS_EVOLVE_KEY_ID", "K_evolve_test")
    monkeypatch.setenv("KAIROS_EVOLVE_PRIVATE_KEY_HEX", "33" * 32)
    monkeypatch.setenv("KAIROS_EVOLVE_GATEWAY_BASE_URL", "http://gateway-test.invalid/api")
    monkeypatch.setenv("KAIROS_GATEWAY_KEY_ID", "K_gw_test")
    monkeypatch.setenv("KAIROS_GATEWAY_PUBLIC_KEY_HEX", gateway_public_key_hex)

    app = build_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
