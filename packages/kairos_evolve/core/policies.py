"""L3 routing policy — Hebbian update + version-bump decision.

In-process state machine ported from kairos main's
`kairos_harness.optimizer.l3_routing.OptimizerL3`. Pure logic, no DB —
storage is handled by `core/routing_store.py`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from kairos_evolve.core.routing_contracts import RoutingEvent, RoutingPolicy


@dataclass(frozen=True)
class HebbianUpdater:
    """Per-event reward/penalty on (routed, accepted) outcomes."""

    reward: float = 0.05
    penalty: float = 0.05
    floor: float = 0.5
    ceiling: float = 2.0

    def apply(
        self,
        *,
        baseline: RoutingPolicy,
        events: Iterable[RoutingEvent],
    ) -> tuple[RoutingPolicy, dict[str, float]]:
        """Apply events to baseline, returning (new_policy, per_skill_deltas)."""
        deltas: dict[str, float] = defaultdict(float)
        for ev in events:
            if ev.accepted_skill_id is None or ev.accepted_skill_id == ev.routed_skill_id:
                deltas[ev.routed_skill_id] += self.reward
            else:
                deltas[ev.routed_skill_id] -= self.penalty
                deltas[ev.accepted_skill_id] += self.reward

        new_weights = dict(baseline.description_weights)
        for sid, d in deltas.items():
            current = new_weights.get(sid, 1.0)
            new_weights[sid] = max(self.floor, min(self.ceiling, current + d))

        new_policy = RoutingPolicy(
            description_weights=new_weights,
            trigger_hints=dict(baseline.trigger_hints),
        )
        return new_policy, dict(deltas)


@dataclass(frozen=True)
class PolicyBumpDecision:
    """Decision to publish a new policy_version based on accumulated deltas."""

    should_bump: bool = False
    driving_skill_id: str | None = None
    max_abs_delta: float = 0.0

    @classmethod
    def should_bump(  # noqa: F811
        cls,
        *,
        deltas: dict[str, float],
        max_abs_delta_threshold: float = 0.1,
    ) -> PolicyBumpDecision:
        if not deltas:
            return cls(should_bump=False, driving_skill_id=None, max_abs_delta=0.0)
        sid, mag = max(deltas.items(), key=lambda kv: abs(kv[1]))
        if abs(mag) >= max_abs_delta_threshold:
            return cls(should_bump=True, driving_skill_id=sid, max_abs_delta=abs(mag))
        return cls(should_bump=False, driving_skill_id=sid, max_abs_delta=abs(mag))


__all__ = ["HebbianUpdater", "PolicyBumpDecision"]
