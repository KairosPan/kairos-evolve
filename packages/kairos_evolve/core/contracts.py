"""Cross-service wire contracts.

Phase 1 shipped EnvelopeV1.
Phase 2A adds RoutingEvent + RoutingPolicy (consumed by the L3 routing API).
Later phases will add ShadowRecord (L4), SynthesisProposal (L5),
L6Proposal (L6) as their consumers land.
"""

from __future__ import annotations

from kairos_evolve.core.envelope import (
    DEFAULT_TTL,
    FUTURE_SKEW,
    EnvelopeV1,
    EnvelopeVerifyError,
    canonical_json,
    merkle_root,
    sign_envelope,
    verify_envelope,
)
from kairos_evolve.core.routing_contracts import RoutingEvent, RoutingPolicy

__all__ = [
    "DEFAULT_TTL",
    "FUTURE_SKEW",
    "EnvelopeV1",
    "EnvelopeVerifyError",
    "RoutingEvent",
    "RoutingPolicy",
    "canonical_json",
    "merkle_root",
    "sign_envelope",
    "verify_envelope",
]
