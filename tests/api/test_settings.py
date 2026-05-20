"""Settings env loader tests."""

from __future__ import annotations

import pytest
from kairos_evolve.api.settings import Settings
from pydantic import ValidationError


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("KAIROS_EVOLVE_NEON_URL", "postgresql://localhost/test")
    monkeypatch.setenv("KAIROS_EVOLVE_KEY_ID", "K_evolve")
    monkeypatch.setenv("KAIROS_EVOLVE_PRIVATE_KEY_HEX", "11" * 32)
    monkeypatch.setenv("KAIROS_EVOLVE_GATEWAY_BASE_URL", "https://gw.example/api")
    monkeypatch.setenv("KAIROS_GATEWAY_KEY_ID", "K_gw")
    monkeypatch.setenv("KAIROS_GATEWAY_PUBLIC_KEY_HEX", "22" * 32)

    s = Settings()
    assert s.neon_url == "postgresql://localhost/test"
    assert s.evolve_key_id == "K_evolve"
    assert s.gateway_base_url == "https://gw.example/api"
    assert s.gateway_key_id == "K_gw"
    assert s.idempotency_ttl_days == 30  # default


def test_settings_missing_required_raises(monkeypatch):
    for k in (
        "KAIROS_EVOLVE_NEON_URL",
        "KAIROS_EVOLVE_KEY_ID",
        "KAIROS_EVOLVE_PRIVATE_KEY_HEX",
        "KAIROS_EVOLVE_GATEWAY_BASE_URL",
        "KAIROS_GATEWAY_KEY_ID",
        "KAIROS_GATEWAY_PUBLIC_KEY_HEX",
    ):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_loads_private_key_bytes(monkeypatch):
    monkeypatch.setenv("KAIROS_EVOLVE_NEON_URL", "postgresql://localhost/test")
    monkeypatch.setenv("KAIROS_EVOLVE_KEY_ID", "K_evolve")
    monkeypatch.setenv("KAIROS_EVOLVE_PRIVATE_KEY_HEX", "ab" * 32)
    monkeypatch.setenv("KAIROS_EVOLVE_GATEWAY_BASE_URL", "https://gw.example/api")
    monkeypatch.setenv("KAIROS_GATEWAY_KEY_ID", "K_gw")
    monkeypatch.setenv("KAIROS_GATEWAY_PUBLIC_KEY_HEX", "cd" * 32)
    s = Settings()
    assert s.evolve_private_key_bytes == bytes.fromhex("ab" * 32)
    assert s.gateway_public_key_bytes == bytes.fromhex("cd" * 32)
