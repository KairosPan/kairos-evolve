"""L3 policy updater tests — Hebbian + threshold-triggered version bump."""

from __future__ import annotations

from dataclasses import dataclass

from kairos_evolve.core.policies import HebbianUpdater, PolicyBumpDecision
from kairos_evolve.core.routing_contracts import RoutingEvent, RoutingPolicy


@dataclass
class _Ev:
    routed: str
    accepted: str | None


def _events(*pairs: _Ev) -> list[RoutingEvent]:
    return [
        RoutingEvent(query=f"q-{i}", routed_skill_id=p.routed, accepted_skill_id=p.accepted)
        for i, p in enumerate(pairs)
    ]


def test_user_accepts_routed_skill_reinforces():
    upd = HebbianUpdater(reward=0.1, penalty=0.1, floor=0.5, ceiling=2.0)
    new_policy, deltas = upd.apply(
        baseline=RoutingPolicy(),
        events=_events(_Ev("a", None), _Ev("a", None)),
    )
    assert new_policy.description_weights["a"] == 1.2  # 1.0 + 0.1 + 0.1
    assert deltas == {"a": 0.2}


def test_user_overrides_penalize_routed_reward_accepted():
    upd = HebbianUpdater(reward=0.1, penalty=0.1, floor=0.5, ceiling=2.0)
    new_policy, deltas = upd.apply(
        baseline=RoutingPolicy(),
        events=_events(_Ev("a", "b")),
    )
    assert new_policy.description_weights["a"] == 0.9
    assert new_policy.description_weights["b"] == 1.1
    assert deltas == {"a": -0.1, "b": 0.1}


def test_clamps_to_ceiling():
    upd = HebbianUpdater(reward=0.5, penalty=0.1, floor=0.5, ceiling=1.2)
    new_policy, _ = upd.apply(
        baseline=RoutingPolicy(description_weights={"a": 1.0}),
        events=_events(_Ev("a", None), _Ev("a", None)),
    )
    assert new_policy.description_weights["a"] == 1.2  # 1.0 + 0.5 + 0.5 clamped to 1.2


def test_clamps_to_floor():
    upd = HebbianUpdater(reward=0.0, penalty=0.5, floor=0.5, ceiling=2.0)
    new_policy, _ = upd.apply(
        baseline=RoutingPolicy(description_weights={"a": 1.0}),
        events=_events(_Ev("a", "b"), _Ev("a", "b")),
    )
    assert new_policy.description_weights["a"] == 0.5


def test_policy_bump_decision_no_bump_below_threshold():
    decision = PolicyBumpDecision.should_bump(
        deltas={"a": 0.03},
        max_abs_delta_threshold=0.1,
    )
    assert decision.should_bump is False


def test_policy_bump_decision_bump_when_threshold_crossed():
    decision = PolicyBumpDecision.should_bump(
        deltas={"a": 0.15, "b": -0.02},
        max_abs_delta_threshold=0.1,
    )
    assert decision.should_bump is True
    assert decision.driving_skill_id == "a"
