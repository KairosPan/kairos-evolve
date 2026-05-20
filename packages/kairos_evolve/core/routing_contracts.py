"""Routing contracts — peer of kairos main's optimizer.contracts.routing.

Wire-format MUST stay byte-identical to the main repo's Pydantic models;
proven by the schema drift detector (tests/contract/test_routing_contracts_drift.py)
and the cross-repo envelope tests that already validate canonical_json behavior.

Note: `description_weights` is a plain `dict[str, float]` here, not a
`defaultdict`. Default-to-1.0 on missing keys is a runtime concern handled in
`core/policies.py`, not a contract concern.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RoutingEvent(BaseModel):
    """A single routing outcome: which skill was routed to, which was accepted."""

    model_config = ConfigDict(frozen=True)

    query: str
    routed_skill_id: str
    accepted_skill_id: str | None = None
    at: Annotated[datetime, Field(default_factory=_utc_now)]


class RoutingPolicy(BaseModel):
    """Per-skill biases blended with semantic match by the SkillRouter.

    `description_weights[skill_id]` is multiplied into the description-match
    score; missing keys default to 1.0 at lookup time (see OptimizerL3 runtime).
    `trigger_hints[skill_id]` are extra routing-only phrases.
    """

    description_weights: dict[str, float] = Field(default_factory=dict)
    trigger_hints: dict[str, list[str]] = Field(default_factory=dict)


__all__ = ["RoutingEvent", "RoutingPolicy"]
