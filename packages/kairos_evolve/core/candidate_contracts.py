"""Candidate-return contract — peer of kairos main's optimizer.contracts.candidate.

The matter-free body the /v1/jobs/run producer signs with K_evolve and POSTs to
the gateway /v1/webhooks/jobs-finished intake (Slice 9 / #34).

Wire-format MUST stay byte-identical to the main repo's Pydantic model; proven
by the schema drift detector (tests/contract/test_candidate_contract_drift.py).
If kairos main bumps candidate.json, run scripts/regen-contracts.sh and confirm
this model still matches.

- ``job_id`` is the correlation key (idempotent intake replays on it; D9).
- ``org_id`` is the org binding carried in the signed body (D8).
- The body is D11-clean: NO matter content (no documents/facts/case).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CandidateReturn(BaseModel):
    """One evolved skill-body candidate returned from kairos-evolve."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    org_id: str
    skill_id: str
    candidate_text: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    spend_usd: float


__all__ = ["CandidateReturn"]
