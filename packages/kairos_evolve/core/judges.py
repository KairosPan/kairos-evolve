"""LLM-as-judge implementations.

DSPy and OpenAI are imported lazily inside methods so this module is safe to
import in the `[api]`-only install. Calling DSPyLLMJudge.score() without the
[cli] extras raises a clear RuntimeError.
"""

from __future__ import annotations

from dataclasses import dataclass

from kairos_evolve.core.fitness import FitnessResult


class CLIExtraNotInstalledError(RuntimeError):
    """Raised when a CLI-only dependency (dspy, openai) is missing at call time."""


@dataclass
class DSPyLLMJudge:
    """LLM-as-judge using DSPy ChainOfThought.

    Constructor does not import dspy. score() does. If [cli] extras are missing,
    score() raises CLIExtraNotInstalledError with install hint.
    """

    eval_model: str

    def score(
        self,
        *,
        task_input: str,
        expected_behavior: str,
        agent_output: str,
        skill_text: str,
    ) -> FitnessResult:
        try:
            import dspy
        except ImportError as exc:
            raise CLIExtraNotInstalledError(
                'dspy-ai is not installed. Run `pip install -e ".[cli]"`.'
            ) from exc

        class _JudgeSig(dspy.Signature):
            """Evaluate an agent's response against an expected-behavior rubric."""

            task_input: str = dspy.InputField()
            expected_behavior: str = dspy.InputField()
            agent_output: str = dspy.InputField()
            skill_text: str = dspy.InputField()
            correctness: float = dspy.OutputField(desc="0.0-1.0")
            procedure_following: float = dspy.OutputField(desc="0.0-1.0")
            conciseness: float = dspy.OutputField(desc="0.0-1.0")
            feedback: str = dspy.OutputField(desc="actionable feedback")

        lm = dspy.LM(self.eval_model)
        with dspy.context(lm=lm):
            judge = dspy.ChainOfThought(_JudgeSig)
            result = judge(
                task_input=task_input,
                expected_behavior=expected_behavior,
                agent_output=agent_output,
                skill_text=skill_text,
            )

        return FitnessResult(
            correctness=_clamp01(result.correctness),
            procedure_following=_clamp01(result.procedure_following),
            conciseness=_clamp01(result.conciseness),
            feedback=str(result.feedback),
        )


def _clamp01(value: object) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, v))


__all__ = ["CLIExtraNotInstalledError", "DSPyLLMJudge"]
