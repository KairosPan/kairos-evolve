"""Runner — Protocol + concrete implementations for evaluating a candidate skill.

Phase 1 provides:
  - Runner Protocol (the contract)
  - FakeRunner (deterministic, for tests + dry-run mode)
  - KairosSubprocessRunner (shells out to `uv run kairos run` in a kairos checkout)

Phase 2 may add an in-process runner that imports kairos-harness directly,
but Phase 1 keeps the dependency at "the kairos CLI is installed in the
kairos checkout you point at".
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RunResult:
    succeeded: bool
    output_text: str
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "succeeded": self.succeeded,
            "output_text": self.output_text,
            "error": self.error,
            "raw": self.raw,
        }


@runtime_checkable
class Runner(Protocol):
    """Anything that can evaluate one (skill_dir, inputs) → RunResult."""

    def run(self, *, skill_dir: Path, inputs: dict[str, Any]) -> RunResult: ...


@dataclass
class FakeRunner:
    """Deterministic in-memory runner for tests + dry-run mode."""

    output_text: str = ""
    succeeded: bool = True
    calls: list[dict[str, Any]] = field(default_factory=list)

    def run(self, *, skill_dir: Path, inputs: dict[str, Any]) -> RunResult:
        self.calls.append({"skill_dir": str(skill_dir), "inputs": dict(inputs)})
        return RunResult(succeeded=self.succeeded, output_text=self.output_text, error=None)


@dataclass
class KairosSubprocessRunner:
    """Shell out to `uv run kairos run <skill_dir> --inputs <json> --matter-id <id>`.

    The kairos checkout is expected to have its uv venv set up. If the subprocess
    fails to launch (uv missing, kairos CLI missing, etc.), the result is a
    succeeded=False RunResult with the error message — never a raised exception,
    so the evolve loop can record and continue.
    """

    kairos_repo: Path
    matter_id: str = "public"
    uv_command: str = "uv"
    timeout_seconds: float = 120.0

    def run(self, *, skill_dir: Path, inputs: dict[str, Any]) -> RunResult:
        cmd = [
            self.uv_command,
            "run",
            "kairos",
            "run",
            str(skill_dir),
            "--inputs",
            json.dumps(inputs),
            "--matter-id",
            self.matter_id,
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.kairos_repo),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as e:
            return RunResult(succeeded=False, output_text="", error=f"{type(e).__name__}: {e}")
        except subprocess.TimeoutExpired:
            return RunResult(
                succeeded=False, output_text="", error=f"timeout after {self.timeout_seconds}s"
            )

        if proc.returncode != 0:
            return RunResult(
                succeeded=False,
                output_text=proc.stdout,
                error=proc.stderr.strip() or f"exit code {proc.returncode}",
            )

        return RunResult(
            succeeded=True,
            output_text=proc.stdout,
            error=None,
            raw={"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode},
        )


__all__ = ["FakeRunner", "KairosSubprocessRunner", "RunResult", "Runner"]
