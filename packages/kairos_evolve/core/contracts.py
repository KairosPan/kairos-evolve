"""Cross-service wire contracts.

Phase 1 only consumes EnvelopeV1 (used by api/envelope-verifying middleware
in Phase 2+; in Phase 1 it is exercised by the cross-repo fixture tests).

L3-L6 contracts (RoutingPolicy, ShadowRecord, SynthesisProposal, L6Proposal)
land here in their respective implementation phases when api routes consume
them.
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
