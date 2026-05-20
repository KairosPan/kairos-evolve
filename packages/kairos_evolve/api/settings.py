"""evolve-api settings loaded from env vars via pydantic-settings.

Production: env vars come from Infisical secrets injected by Modal at deploy
time. Tests set them via `monkeypatch.setenv`.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """env-loaded configuration for evolve-api."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # Neon
    neon_url: str = Field(alias="KAIROS_EVOLVE_NEON_URL")

    # evolve key (signs outgoing envelopes; verifies its own)
    evolve_key_id: str = Field(alias="KAIROS_EVOLVE_KEY_ID")
    evolve_private_key_hex: str = Field(alias="KAIROS_EVOLVE_PRIVATE_KEY_HEX")

    # Gateway (incoming envelopes are verified against this; webhooks go here)
    gateway_base_url: str = Field(alias="KAIROS_EVOLVE_GATEWAY_BASE_URL")
    gateway_key_id: str = Field(alias="KAIROS_GATEWAY_KEY_ID")
    gateway_public_key_hex: str = Field(alias="KAIROS_GATEWAY_PUBLIC_KEY_HEX")

    # Tunables
    idempotency_ttl_days: int = 30
    policy_bump_delta_threshold: float = 0.1
    routing_event_batch_max_size: int = 1000

    @property
    def evolve_private_key_bytes(self) -> bytes:
        return bytes.fromhex(self.evolve_private_key_hex)

    @property
    def gateway_public_key_bytes(self) -> bytes:
        return bytes.fromhex(self.gateway_public_key_hex)

    @property
    def idempotency_ttl(self) -> timedelta:
        return timedelta(days=self.idempotency_ttl_days)


__all__ = ["Settings"]
