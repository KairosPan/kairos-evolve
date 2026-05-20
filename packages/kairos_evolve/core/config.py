"""Configuration resolution for kairos-evolve.

Phase 1: minimal — just enough to find a kairos checkout and detect optional
LLM credentials. Phase 2+ adds Neon credentials, key vault references, etc.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class MissingKairosRepoError(RuntimeError):
    """Raised when neither --kairos-repo nor KAIROS_REPO resolves to a valid kairos checkout."""


@dataclass(frozen=True)
class EvolveConfig:
    """Resolved configuration for an evolve invocation."""

    kairos_repo: Path
    has_openai_key: bool

    @classmethod
    def resolve(cls, *, kairos_repo: Path | None = None) -> EvolveConfig:
        """Resolve kairos_repo from (1) explicit arg, (2) KAIROS_REPO env, then validate."""
        if kairos_repo is None:
            env_val = os.environ.get("KAIROS_REPO")
            if not env_val:
                raise MissingKairosRepoError(
                    "kairos_repo unset: pass --kairos-repo or set KAIROS_REPO env"
                )
            kairos_repo = Path(env_val)
        kairos_repo = kairos_repo.expanduser().resolve()
        if not (kairos_repo / "skills").is_dir():
            raise MissingKairosRepoError(
                f"{kairos_repo} is not a kairos checkout (no skills/ directory)"
            )
        return cls(
            kairos_repo=kairos_repo,
            has_openai_key=bool(os.environ.get("OPENAI_API_KEY")),
        )


__all__ = ["EvolveConfig", "MissingKairosRepoError"]
