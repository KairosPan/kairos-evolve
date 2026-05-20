"""L1 prompts evolution loop.

Read baseline prompt → generate N candidates via a PromptRewriter →
evaluate each via a Runner + scorer → pick the best. PromptRewriter and
Runner are Protocols so tests inject deterministic fakes and the CLI wires
in real DSPy+GEPA + KairosSubprocessRunner.

This module is pure — no LLM imports here. The real DSPy+GEPA rewriter is
factory-built by the CLI (Task 14) and lazy-imports dspy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kairos_evolve.core.fitness import FitnessResult
from kairos_evolve.core.runner import Runner
from kairos_evolve.core.skill_io import find_skill, load_skill, read_prompt


@dataclass(frozen=True)
class PromptCandidate:
    name: str
    new_text: str
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("PromptCandidate.name must be non-empty")


class PromptRewriter(Protocol):
    """Generates N candidate rewrites for a single prompt file."""

    def rewrite(self, *, original: str, hint: str, n: int) -> list[PromptCandidate]: ...


Scorer = Callable[[str, str, object], FitnessResult]
# Scorer(baseline_text, candidate_text, run_result) -> FitnessResult


@dataclass(frozen=True)
class EvolveResult:
    skill_name: str
    baseline_score: float
    evolved_score: float
    winner: PromptCandidate | None  # None if no candidate beat baseline
    baseline_text: str
    candidates_explored: list[tuple[PromptCandidate, float]]


def evolve_prompts(
    *,
    skill_name: str,
    kairos_repo: Path,
    rewriter: PromptRewriter,
    runner: Runner,
    scorer: Scorer,
    n_candidates: int = 5,
    prompt_filename: str = "system.md",
    eval_inputs: dict[str, object] | None = None,
    hint: str = "improve correctness and conciseness",
) -> EvolveResult:
    """Run one L1 evolve iteration on a single skill's prompt file.

    Returns an EvolveResult describing baseline + winner (or None) + explored
    candidates. Does NOT write anything to disk — the CLI does that.
    """
    eval_inputs = eval_inputs or {}
    skill_dir = find_skill(skill_name, kairos_repo=kairos_repo)
    skill = load_skill(skill_dir)
    baseline_text = read_prompt(skill_dir, prompt_filename)

    baseline_run = runner.run(skill_dir=skill_dir, inputs=eval_inputs)
    baseline_fit = scorer(baseline_text, baseline_text, baseline_run)
    baseline_score = baseline_fit.composite()

    candidates = rewriter.rewrite(original=baseline_text, hint=hint, n=n_candidates)
    explored: list[tuple[PromptCandidate, float]] = []
    best_candidate_score: float | None = None
    best_winner_score = baseline_score
    winner: PromptCandidate | None = None

    for cand in candidates:
        cand_run = runner.run(skill_dir=skill_dir, inputs=eval_inputs)
        cand_fit = scorer(baseline_text, cand.new_text, cand_run)
        cand_score = cand_fit.composite()
        explored.append((cand, cand_score))
        # Track best candidate score regardless of whether it beats baseline
        if best_candidate_score is None or cand_score > best_candidate_score:
            best_candidate_score = cand_score
        # Track winner only when candidate strictly beats baseline
        if cand_score > best_winner_score:
            best_winner_score = cand_score
            winner = cand

    # evolved_score reflects the best candidate score found (may be < baseline)
    evolved_score = best_candidate_score if best_candidate_score is not None else baseline_score

    return EvolveResult(
        skill_name=skill.name,
        baseline_score=baseline_score,
        evolved_score=evolved_score,
        winner=winner,
        baseline_text=baseline_text,
        candidates_explored=explored,
    )


__all__ = ["EvolveResult", "PromptCandidate", "PromptRewriter", "Scorer", "evolve_prompts"]
