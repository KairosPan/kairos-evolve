"""Fitness scoring — protocol + pure-Python helpers, no LLM imports here.

LLM-as-judge implementation lives in core/judges.py (lazy-imported only by the
CLI path so the api install profile does not pull dspy-ai).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FitnessResult:
    """Multi-dimensional fitness score for an evolved candidate."""

    correctness: float = 0.0
    procedure_following: float = 0.0
    conciseness: float = 0.0
    length_penalty: float = 0.0
    feedback: str = ""

    def composite(
        self,
        *,
        w_correctness: float = 0.5,
        w_procedure: float = 0.3,
        w_conciseness: float = 0.2,
    ) -> float:
        raw = (
            w_correctness * self.correctness
            + w_procedure * self.procedure_following
            + w_conciseness * self.conciseness
        )
        return max(0.0, raw - self.length_penalty)


_TOKEN_RE = re.compile(r"[a-zA-Z]{2,}")


def keyword_overlap_score(*, expected: str, actual: str) -> float:
    """Fraction of expected vocabulary that appears in actual.

    Returns 0.0 if expected is empty. Case-insensitive.
    """
    expected_set = set(_TOKEN_RE.findall(expected.lower()))
    if not expected_set:
        return 0.0
    actual_set = set(_TOKEN_RE.findall(actual.lower()))
    return len(expected_set & actual_set) / len(expected_set)


def length_penalty(*, actual_size: int, max_size: int) -> float:
    """Penalty ramps from 0 at 90 % of max_size to 0.3 at 100 %+ (clamped)."""
    if max_size <= 0:
        return 0.0
    ratio = actual_size / max_size
    if ratio <= 0.9:
        return 0.0
    return min(0.3, (ratio - 0.9) * 3.0)


def weighted_composite(scores: dict[str, float], *, weights: dict[str, float]) -> float:
    total_w = sum(weights.values())
    if total_w == 0:
        return 0.0
    return sum(scores.get(k, 0.0) * w for k, w in weights.items()) / total_w


__all__ = ["FitnessResult", "keyword_overlap_score", "length_penalty", "weighted_composite"]
