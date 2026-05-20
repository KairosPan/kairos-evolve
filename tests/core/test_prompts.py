"""prompts module — L1 evolve loop with fake rewriter + fake runner."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from kairos_evolve.core.fitness import FitnessResult
from kairos_evolve.core.prompts import (
    EvolveResult,
    PromptCandidate,
    evolve_prompts,
)
from kairos_evolve.core.runner import FakeRunner


@dataclass
class FakePromptRewriter:
    """Deterministic rewriter that returns N pre-canned candidates."""

    candidates: list[PromptCandidate]

    def rewrite(self, *, original: str, hint: str, n: int) -> list[PromptCandidate]:
        return self.candidates[:n]


def test_evolve_prompts_returns_baseline_score_and_best(fake_kairos_repo):
    rewriter = FakePromptRewriter(
        candidates=[
            PromptCandidate(name="system.md", new_text="evolved 1", rationale="r1"),
            PromptCandidate(name="system.md", new_text="evolved 2", rationale="r2"),
        ]
    )
    runner = FakeRunner(output_text="ok")

    result = evolve_prompts(
        skill_name="statute-compare",
        kairos_repo=fake_kairos_repo,
        rewriter=rewriter,
        runner=runner,
        n_candidates=2,
        scorer=lambda baseline, candidate, run: FitnessResult(
            correctness=0.8 if "evolved 2" in candidate else 0.5,
            procedure_following=0.8,
            conciseness=0.9,
        ),
    )
    assert isinstance(result, EvolveResult)
    assert result.skill_name == "statute-compare"
    assert result.baseline_score > 0
    assert result.evolved_score >= result.baseline_score
    assert "evolved 2" in result.winner.new_text


def test_evolve_prompts_no_improvement_keeps_baseline(fake_kairos_repo):
    rewriter = FakePromptRewriter(
        candidates=[PromptCandidate(name="system.md", new_text="worse", rationale="")]
    )
    runner = FakeRunner(output_text="ok")

    result = evolve_prompts(
        skill_name="statute-compare",
        kairos_repo=fake_kairos_repo,
        rewriter=rewriter,
        runner=runner,
        n_candidates=1,
        scorer=lambda baseline, candidate, run: FitnessResult(
            correctness=0.9 if candidate == baseline else 0.1,
            procedure_following=0.5,
            conciseness=0.5,
        ),
    )
    assert result.winner is None
    assert result.evolved_score < result.baseline_score


def test_prompt_candidate_validates_name():
    with pytest.raises(ValueError):
        PromptCandidate(name="", new_text="x", rationale="")
