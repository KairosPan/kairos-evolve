"""EnvelopeV1 — ed25519 cross-service signing wire format.

Peer implementation of
`kairos_harness.optimizer.contracts.envelope` in the main kairos repo.
Wire-format MUST stay byte-identical to that module — proven by the shared
`shared/envelope/v1/*.json` fixtures and the schema drift test.

Canonical signing input (the bytes signed by ed25519):

    canonical = canonical_json({
        "version": "v1",
        "key_id":  <key_id>,
        "service_id": <service_id>,
        "ts": <ts ISO8601 UTC, second precision>,
        "nonce": <16 bytes, base64 standard>,
        "body_sha256": <hex sha256 of canonical_json(body)>,
    })

canonical_json rules:
  - utf-8 encoded
  - object keys sorted (recursively)
  - no whitespace (compact separators)
  - integers / floats serialized via json default
  - tuples serialized as lists

verify_envelope rejects when:
  - signature does not verify against canonical
  - body_sha256 != hex(sha256(canonical_json(provided body)))
  - ts older than now - DEFAULT_TTL (5 minutes by default)
  - ts more than 60 seconds in the future

See kairos design spec §3.7 (signing strategy) and §5.2 (key management).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_TTL: timedelta = timedelta(minutes=5)
FUTURE_SKEW: timedelta = timedelta(seconds=60)


class EnvelopeVerifyError(Exception):
    """Raised by verify_envelope when an envelope fails validation."""


class EnvelopeV1(BaseModel):
    """The signed envelope carried on every cross-service action."""

    model_config = ConfigDict(frozen=True)

    version: Annotated[str, Field(pattern=r"^v1$")]
    key_id: str
    service_id: str
    ts: datetime
    nonce: str
    body_sha256: str
    signature: str


def canonical_json(obj: object) -> bytes:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, datetime):
        return _serialize_ts(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _serialize_ts(ts: datetime) -> str:
    if ts.tzinfo is None:
        raise ValueError("envelope ts must be timezone-aware UTC")
    return ts.astimezone(UTC).replace(microsecond=0).isoformat()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _signing_payload(
    *,
    key_id: str,
    service_id: str,
    ts: datetime,
    nonce: str,
    body_sha256: str,
) -> bytes:
    return canonical_json(
        {
            "version": "v1",
            "key_id": key_id,
            "service_id": service_id,
            "ts": _serialize_ts(ts),
            "nonce": nonce,
            "body_sha256": body_sha256,
        }
    )


def sign_envelope(
    *,
    body: object,
    key: Ed25519PrivateKey,
    key_id: str,
    service_id: str,
    ts: datetime | None = None,
    nonce: bytes | None = None,
) -> EnvelopeV1:
    """Produce an EnvelopeV1 over `body`, signed with `key`."""
    ts = ts or datetime.now(UTC)
    nonce_b = nonce or secrets.token_bytes(16)
    nonce_str = base64.b64encode(nonce_b).decode("ascii")
    body_sha = _sha256_hex(canonical_json(body))
    payload = _signing_payload(
        key_id=key_id,
        service_id=service_id,
        ts=ts,
        nonce=nonce_str,
        body_sha256=body_sha,
    )
    sig = key.sign(payload)
    return EnvelopeV1(
        version="v1",
        key_id=key_id,
        service_id=service_id,
        ts=ts,
        nonce=nonce_str,
        body_sha256=body_sha,
        signature=base64.b64encode(sig).decode("ascii"),
    )


def verify_envelope(
    envelope: EnvelopeV1,
    *,
    body: object,
    public_key: Ed25519PublicKey,
    ttl: timedelta = DEFAULT_TTL,
    now: datetime | None = None,
) -> None:
    """Raise EnvelopeVerifyError if envelope does not validate over body."""
    now = now or datetime.now(UTC)
    age = now - envelope.ts
    if age > ttl:
        raise EnvelopeVerifyError(f"envelope expired: age={age} > ttl={ttl}")
    if -age > FUTURE_SKEW:
        raise EnvelopeVerifyError(f"envelope ts in the future: {-age} > skew={FUTURE_SKEW}")
    expected_body_sha = _sha256_hex(canonical_json(body))
    if envelope.body_sha256 != expected_body_sha:
        raise EnvelopeVerifyError(
            f"body_sha256 mismatch: envelope={envelope.body_sha256} computed={expected_body_sha}"
        )
    payload = _signing_payload(
        key_id=envelope.key_id,
        service_id=envelope.service_id,
        ts=envelope.ts,
        nonce=envelope.nonce,
        body_sha256=envelope.body_sha256,
    )
    try:
        public_key.verify(base64.b64decode(envelope.signature), payload)
    except InvalidSignature as exc:
        raise EnvelopeVerifyError("signature did not verify") from exc


def merkle_root(members: list[bytes]) -> str:
    """Compute a deterministic Merkle root over an ordered list of member bytes."""
    if not members:
        raise ValueError("merkle_root requires at least one member")
    layer = [hashlib.sha256(m).digest() for m in members]
    while len(layer) > 1:
        nxt: list[bytes] = []
        for i in range(0, len(layer), 2):
            a = layer[i]
            b = layer[i + 1] if i + 1 < len(layer) else a
            nxt.append(hashlib.sha256(a + b).digest())
        layer = nxt
    return layer[0].hex()


__all__ = [
    "DEFAULT_TTL",
    "FUTURE_SKEW",
    "EnvelopeV1",
    "EnvelopeVerifyError",
    "canonical_json",
    "merkle_root",
    "sign_envelope",
    "verify_envelope",
]
