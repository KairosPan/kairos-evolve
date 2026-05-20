"""skill_io tests — find + load + read prompts."""

from __future__ import annotations

import pytest
from kairos_evolve.core.skill_io import (
    SkillNotFoundError,
    find_skill,
    load_skill,
    read_prompt,
)


def test_find_skill_returns_path(fake_kairos_repo):
    path = find_skill("statute-compare", kairos_repo=fake_kairos_repo)
    assert path.name == "statute-compare"
    assert path.is_dir()


def test_find_skill_raises_when_missing(fake_kairos_repo):
    with pytest.raises(SkillNotFoundError, match="not-a-skill"):
        find_skill("not-a-skill", kairos_repo=fake_kairos_repo)


def test_load_skill_parses_frontmatter(fake_kairos_repo):
    skill_dir = find_skill("statute-compare", kairos_repo=fake_kairos_repo)
    skill = load_skill(skill_dir)
    assert skill.name == "statute-compare"
    assert skill.version == "0.1.0"
    assert skill.frontmatter["risk_tier"] == "medium"
    assert "Compare provisions" in skill.body


def test_read_prompt_returns_file_text(fake_kairos_repo):
    skill_dir = find_skill("statute-compare", kairos_repo=fake_kairos_repo)
    text = read_prompt(skill_dir, "system.md")
    assert "careful legal-research assistant" in text


def test_read_prompt_raises_for_missing_file(fake_kairos_repo):
    skill_dir = find_skill("statute-compare", kairos_repo=fake_kairos_repo)
    with pytest.raises(FileNotFoundError, match=r"no-such-prompt\.md"):
        read_prompt(skill_dir, "no-such-prompt.md")
