"""Read SKILL.md + prompts/ from a kairos checkout.

Phase 1 only consumes the frontmatter dict + the raw body string and the raw
prompt-file text — it does NOT import kairos-skill-sdk. The plan is to keep
kairos-evolve light, with no runtime dependency on the kairos workspace.

If validation grows complex enough to warrant kairos-skill-sdk in the future,
it lands as an optional extra (e.g., `pip install kairos-evolve[skill-sdk]`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class SkillNotFoundError(FileNotFoundError):
    """Raised when find_skill cannot locate <kairos_repo>/skills/<name>/SKILL.md."""


@dataclass(frozen=True)
class Skill:
    """A loaded SKILL.md plus its source dir."""

    directory: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def name(self) -> str:
        return str(self.frontmatter.get("name", ""))

    @property
    def version(self) -> str:
        return str(self.frontmatter.get("version", ""))


def find_skill(name: str, *, kairos_repo: Path) -> Path:
    """Resolve <kairos_repo>/skills/<name>/SKILL.md to its containing dir."""
    candidate = kairos_repo / "skills" / name
    if not (candidate / "SKILL.md").is_file():
        raise SkillNotFoundError(f"skill {name!r} not found at {candidate / 'SKILL.md'}")
    return candidate


def load_skill(skill_dir: Path) -> Skill:
    """Parse SKILL.md into (frontmatter dict, body str)."""
    raw = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    head, sep, body = raw.partition("\n---\n")
    if not sep or not head.startswith("---\n"):
        raise ValueError(f"{skill_dir / 'SKILL.md'} missing YAML frontmatter")
    fm = yaml.safe_load(head[4:]) or {}
    if not isinstance(fm, dict):
        raise ValueError(f"{skill_dir / 'SKILL.md'} frontmatter is not a mapping")
    return Skill(directory=skill_dir, frontmatter=fm, body=body.strip())


def read_prompt(skill_dir: Path, prompt_filename: str) -> str:
    """Read skill_dir/prompts/<prompt_filename>. Raises FileNotFoundError if missing."""
    path = skill_dir / "prompts" / prompt_filename
    if not path.is_file():
        raise FileNotFoundError(f"prompt {prompt_filename!r} not in {skill_dir / 'prompts'}")
    return path.read_text(encoding="utf-8")


__all__ = ["Skill", "SkillNotFoundError", "find_skill", "load_skill", "read_prompt"]
