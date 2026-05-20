"""Cross-repo envelope contract tests — run the shared envelope/v1 vectors.

If these fail, the peer ed25519 / canonical-JSON / Merkle implementation has
drifted from kairos main. Treat as a wire-break and revert.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kairos_evolve.core.envelope import (
    EnvelopeV1,
    EnvelopeVerifyError,
    canonical_json,
    merkle_root,
    sign_envelope,
    verify_envelope,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "shared" / "envelope" / "v1"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _keypair_from_hex(seed_hex: str):
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))
    return priv, priv.public_key()


def _envelope_from_fixture(f: dict) -> EnvelopeV1:
    priv, _ = _keypair_from_hex(f["private_key_hex"])
    ts = datetime.fromisoformat(f["ts"])
    nonce = base64.b64decode(f["nonce_b64"])
    return sign_envelope(
        body=f["body"],
        key=priv,
        key_id=f["key_id"],
        service_id=f["service_id"],
        ts=ts,
        nonce=nonce,
    )


def test_sign_verify_fixture():
    f = _load("sign_verify.json")
    env = _envelope_from_fixture(f)
    assert env.body_sha256 == f["expected"]["body_sha256"]
    assert env.signature == f["expected"]["signature"]
    _, pub = _keypair_from_hex(f["private_key_hex"])
    verify_envelope(env, body=f["body"], public_key=pub, now=env.ts)


def test_batch_merkle_fixture():
    f = _load("batch_merkle.json")
    members = [canonical_json(m) for m in f["members"]]
    assert merkle_root(members) == f["expected"]["merkle_root"]


def test_expired_rejected_fixture():
    f = _load("expired_rejected.json")
    env = _envelope_from_fixture(f)
    _, pub = _keypair_from_hex(f["private_key_hex"])
    now = datetime.fromisoformat(f["verify_at"])
    with pytest.raises(EnvelopeVerifyError, match=f["expected"]["error_substring"]):
        verify_envelope(env, body=f["body"], public_key=pub, now=now)


def test_tampered_rejected_fixture():
    f = _load("tampered_rejected.json")
    env = _envelope_from_fixture(f)
    _, pub = _keypair_from_hex(f["private_key_hex"])
    with pytest.raises(EnvelopeVerifyError, match=f["expected"]["error_substring"]):
        verify_envelope(env, body=f["expected"]["tampered_body"], public_key=pub, now=env.ts)


def test_field_order_stable_fixture():
    f = _load("field_order_stable.json")
    env = _envelope_from_fixture(f)
    _, pub = _keypair_from_hex(f["private_key_hex"])
    verify_envelope(env, body=f["expected"]["reordered_body"], public_key=pub, now=env.ts)
