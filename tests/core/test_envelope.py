"""EnvelopeV1 unit tests — peer of kairos main repo's envelope tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kairos_evolve.core.envelope import (
    DEFAULT_TTL,
    EnvelopeV1,
    EnvelopeVerifyError,
    canonical_json,
    merkle_root,
    sign_envelope,
    verify_envelope,
)


@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


def test_canonical_json_sorts_keys():
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_json_no_whitespace():
    assert canonical_json({"x": [1, 2, 3]}) == b'{"x":[1,2,3]}'


def test_canonical_json_unicode_utf8():
    blob = canonical_json({"name": "§301"})
    assert "§".encode() in blob


def test_sign_verify_roundtrip(keypair):
    priv, pub = keypair
    body = {"action": "ping", "scope": "test"}
    env = sign_envelope(body=body, key=priv, key_id="K_t", service_id="s")
    assert env.version == "v1"
    verify_envelope(env, body=body, public_key=pub)


def test_verify_rejects_tamper(keypair):
    priv, pub = keypair
    env = sign_envelope(body={"a": 1}, key=priv, key_id="K", service_id="s")
    with pytest.raises(EnvelopeVerifyError, match="body_sha256"):
        verify_envelope(env, body={"a": 2}, public_key=pub)


def test_verify_rejects_expired(keypair):
    priv, pub = keypair
    env = sign_envelope(
        body={},
        key=priv,
        key_id="K",
        service_id="s",
        ts=datetime.now(UTC) - DEFAULT_TTL - timedelta(seconds=1),
    )
    with pytest.raises(EnvelopeVerifyError, match="expired"):
        verify_envelope(env, body={}, public_key=pub)


def test_field_reorder_still_verifies(keypair):
    priv, pub = keypair
    env = sign_envelope(body={"a": 1, "b": 2}, key=priv, key_id="K", service_id="s")
    verify_envelope(env, body={"b": 2, "a": 1}, public_key=pub)


def test_merkle_single_member():
    import hashlib

    assert merkle_root([b"hi"]) == hashlib.sha256(b"hi").hexdigest()


def test_merkle_order_sensitive():
    assert merkle_root([b"x", b"y"]) != merkle_root([b"y", b"x"])


def test_envelope_v1_json_schema_has_required():
    schema = EnvelopeV1.model_json_schema()
    required = set(schema["required"])
    assert {"key_id", "service_id", "ts", "nonce", "body_sha256", "signature"}.issubset(required)
