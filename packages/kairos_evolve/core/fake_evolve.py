"""Slice 9 (#34) — the FAKE, in-process evolve compute for ``/v1/jobs/run``.

The minimum-slice compute (spec D2): a programmatic wrapper over
``core.prompts.evolve_prompts`` driven by a deterministic fake rewriter + the
heuristic (keyword-overlap) scorer. NO DSPy, NO real GEPA, NO off-request GEPA
worker (the future ECS-Fargate/Batch long-GEPA worker; #35), and NO provisioned
kairos checkout — the real DSPy rewriter + a Runner against a real checkout is #35.

Why a throwaway scratch skill dir? ``evolve_prompts`` is the reusable kernel and
reads its baseline from ``<repo>/skills/<name>/prompts/system.md`` on disk. The
job-run body is D11-clean (it carries only ``skill_id`` / ``target_ref`` — no
prompt text, no matter), so there is nothing to evolve against in-request. We
materialize a tiny synthetic skill in a ``TemporaryDirectory`` purely so the
kernel runs unmodified, then discard it. This is NOT a kairos checkout: it holds
no kairos code and no matter — just a placeholder baseline so the fake rewriter +
heuristic scorer can produce a deterministic candidate. When #35 lands the real
rewriter + Runner against a provisioned checkout, this module is replaced.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from kairos_evolve.core.fitness import FitnessResult, keyword_overlap_score
from kairos_evolve.core.prompts import EvolveResult, PromptCandidate, evolve_prompts
from kairos_evolve.core.runner import FakeRunner

_PROMPT_FILENAME = "system.md"
_BASELINE_TEXT = (
    "You are a careful, well-scoped assistant.\n"
    "Follow the skill's procedure and cite your sources.\n"
)


@dataclass
class _FakeRewriter:
    """Deterministic rewriter (mirrors the CLI's fake strategy)."""

    def rewrite(self, *, original: str, hint: str, n: int) -> list[PromptCandidate]:
        return [
            PromptCandidate(
                name=_PROMPT_FILENAME,
                new_text=f"# v{i + 1} ({hint[:24]})\n\n{original}\n\n— evolved candidate {i + 1}",
                rationale=f"fake rewrite #{i + 1}",
            )
            for i in range(n)
        ]


def _heuristic_scorer(baseline_text: str, candidate_text: str, run_result: object) -> FitnessResult:
    """Cheap proxy: keyword overlap + a conciseness ratio (no LLM judge)."""
    overlap = keyword_overlap_score(expected=baseline_text, actual=candidate_text)
    conciseness_ratio = min(1.0, len(baseline_text) / max(1, len(candidate_text)))
    return FitnessResult(
        correctness=overlap,
        procedure_following=overlap,
        conciseness=conciseness_ratio,
    )


def _write_scratch_skill(repo: Path, skill_id: str) -> None:
    """Materialize a minimal SKILL.md + prompts/system.md so the kernel can read it."""
    skill_dir = repo / "skills" / skill_id
    (skill_dir / "prompts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\nversion: 0.0.0\n---\n\n# {skill_id}\n",
        encoding="utf-8",
    )
    (skill_dir / "prompts" / _PROMPT_FILENAME).write_text(_BASELINE_TEXT, encoding="utf-8")


def run_fake_evolve(*, skill_id: str, n_candidates: int = 3) -> EvolveResult:
    """Run one fake L1 evolve iteration for ``skill_id`` — no checkout, no DSPy.

    Returns an :class:`EvolveResult`; ``winner`` may be ``None`` when no candidate
    beat the synthetic baseline (the fake rewriter pads the baseline, so the
    heuristic scorer usually keeps overlap high while conciseness drops — the
    point is a deterministic, fast candidate, not a real improvement).
    """
    with tempfile.TemporaryDirectory(prefix="evolve-fake-") as tmp:
        repo = Path(tmp)
        _write_scratch_skill(repo, skill_id)
        return evolve_prompts(
            skill_name=skill_id,
            kairos_repo=repo,
            rewriter=_FakeRewriter(),
            runner=FakeRunner(output_text="(fake compute — no real eval)"),
            scorer=_heuristic_scorer,
            n_candidates=n_candidates,
            prompt_filename=_PROMPT_FILENAME,
        )


__all__ = ["run_fake_evolve"]
