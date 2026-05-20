"""`kairos-evolve prompts` — L1 prompts evolution CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from kairos_evolve.core.config import EvolveConfig, MissingKairosRepoError
from kairos_evolve.core.fitness import FitnessResult, keyword_overlap_score
from kairos_evolve.core.prompts import PromptCandidate, evolve_prompts
from kairos_evolve.core.runner import FakeRunner, KairosSubprocessRunner

app = typer.Typer(name="prompts", no_args_is_help=True, add_completion=False)
console = Console()


# ----- Rewriter strategies -----------------------------------------------------


@dataclass
class _FakeRewriter:
    """Deterministic rewriter used when --rewriter=fake or no OPENAI_API_KEY."""

    def rewrite(self, *, original: str, hint: str, n: int) -> list[PromptCandidate]:
        return [
            PromptCandidate(
                name="system.md",
                new_text=f"# v{i + 1} ({hint[:24]})\n\n{original}\n\n— evolved candidate {i + 1}",
                rationale=f"fake rewrite #{i + 1}",
            )
            for i in range(n)
        ]


def _build_dspy_gepa_rewriter(eval_model: str) -> object:
    """Lazy-construct the real DSPy+GEPA rewriter (imports dspy here)."""
    try:
        import dspy  # noqa: F401
    except ImportError as exc:
        raise typer.BadParameter('rewriter=dspy-gepa requires `pip install -e ".[cli]"`') from exc

    @dataclass
    class _DSPyGEPARewriter:
        eval_model: str

        def rewrite(self, *, original: str, hint: str, n: int) -> list[PromptCandidate]:
            import dspy  # local

            class _RewriteSig(dspy.Signature):
                """Propose an improved version of an agent prompt."""

                original_prompt: str = dspy.InputField()
                hint: str = dspy.InputField()
                improved_prompt: str = dspy.OutputField(
                    desc="A revised prompt addressing the hint, same purpose, no new claims."
                )

            lm = dspy.LM(self.eval_model)
            outputs: list[PromptCandidate] = []
            with dspy.context(lm=lm):
                rewriter = dspy.ChainOfThought(_RewriteSig)
                for i in range(n):
                    result = rewriter(original_prompt=original, hint=hint)
                    outputs.append(
                        PromptCandidate(
                            name="system.md",
                            new_text=str(result.improved_prompt),
                            rationale=f"dspy-gepa rewrite #{i + 1}",
                        )
                    )
            return outputs

    return _DSPyGEPARewriter(eval_model=eval_model)


# ----- Scoring -----------------------------------------------------------------


def _heuristic_scorer(baseline_text: str, candidate_text: str, run_result: object) -> FitnessResult:
    """Cheap proxy: keyword overlap baseline vs candidate length.

    Used when no LLM judge is configured. Encourages candidates that retain
    the baseline vocabulary while not blowing up in length.
    """
    overlap = keyword_overlap_score(expected=baseline_text, actual=candidate_text)
    conciseness_ratio = min(1.0, len(baseline_text) / max(1, len(candidate_text)))
    return FitnessResult(
        correctness=overlap,
        procedure_following=overlap,
        conciseness=conciseness_ratio,
    )


# ----- CLI command --------------------------------------------------------------


@app.callback(invoke_without_command=True)
def run(
    skill: Annotated[str, typer.Option("--skill", help="Skill name (matches skills/<name>/)")],
    iterations: Annotated[
        int, typer.Option("--iterations", help="Number of candidates to generate")
    ] = 5,
    rewriter: Annotated[str, typer.Option("--rewriter", help="fake | dspy-gepa")] = "fake",
    eval_model: Annotated[str, typer.Option("--eval-model")] = "openai/gpt-4.1-mini",
    runner_kind: Annotated[str, typer.Option("--runner", help="fake | kairos-subprocess")] = "fake",
    kairos_repo: Annotated[Path | None, typer.Option("--kairos-repo")] = None,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("output"),
) -> None:
    """Run one L1 prompts evolution iteration on a single skill."""
    try:
        cfg = EvolveConfig.resolve(kairos_repo=kairos_repo)
    except MissingKairosRepoError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(code=2) from e

    if rewriter == "fake":
        rw = _FakeRewriter()
    elif rewriter == "dspy-gepa":
        rw = _build_dspy_gepa_rewriter(eval_model=eval_model)
    else:
        raise typer.BadParameter(f"unknown rewriter {rewriter!r}; use fake | dspy-gepa")

    if runner_kind == "fake":
        runner = FakeRunner(output_text="(fake runner — no real eval performed)")
    elif runner_kind == "kairos-subprocess":
        runner = KairosSubprocessRunner(kairos_repo=cfg.kairos_repo, matter_id="public")
    else:
        raise typer.BadParameter(f"unknown runner {runner_kind!r}; use fake | kairos-subprocess")

    console.print(f"[bold cyan]kairos-evolve prompts[/bold cyan] — skill: [bold]{skill}[/bold]")
    console.print(f"  kairos_repo: {cfg.kairos_repo}")
    console.print(f"  rewriter:    {rewriter}")
    console.print(f"  runner:      {runner_kind}")
    console.print(f"  iterations:  {iterations}")

    result = evolve_prompts(
        skill_name=skill,
        kairos_repo=cfg.kairos_repo,
        rewriter=rw,
        runner=runner,
        scorer=_heuristic_scorer,
        n_candidates=iterations,
    )

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / result.skill_name / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "baseline.md").write_text(result.baseline_text, encoding="utf-8")
    if result.winner is not None:
        (run_dir / "evolved.md").write_text(result.winner.new_text, encoding="utf-8")

    metrics = {
        "skill_name": result.skill_name,
        "timestamp": ts,
        "baseline_score": round(result.baseline_score, 4),
        "evolved_score": round(result.evolved_score, 4),
        "improvement": round(result.evolved_score - result.baseline_score, 4),
        "candidates_explored": [
            {"rationale": c.rationale, "score": round(s, 4)} for c, s in result.candidates_explored
        ],
        "winner_rationale": result.winner.rationale if result.winner else None,
        "rewriter": rewriter,
        "runner": runner_kind,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    table = Table(title="Evolution Result")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Baseline", f"{result.baseline_score:.3f}")
    table.add_row("Evolved", f"{result.evolved_score:.3f}")
    table.add_row("Change", f"{result.evolved_score - result.baseline_score:+.3f}")
    table.add_row("Winner", result.winner.rationale if result.winner else "(no improvement)")
    console.print()
    console.print(table)
    console.print(f"\n[green]✓ wrote[/green] {run_dir}/")


__all__ = ["app"]
