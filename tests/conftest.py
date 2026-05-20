"""Shared pytest fixtures for kairos-evolve tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_postgresql import factories

postgresql_proc = factories.postgresql_proc(port=None)


@pytest.fixture
def fake_kairos_repo(tmp_path: Path) -> Path:
    """Build a minimal kairos-repo-shaped directory with one skill."""
    skills = tmp_path / "skills"
    skill_dir = skills / "statute-compare"
    prompts = skill_dir / "prompts"
    prompts.mkdir(parents=True)

    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: statute-compare\n"
        "version: 0.1.0\n"
        "description: Compare two statutory provisions across jurisdictions.\n"
        "jurisdictions: [us]\n"
        "practice_areas: [criminal]\n"
        "risk_tier: medium\n"
        "safety:\n"
        "  citation_verification: required\n"
        "  jurisdiction_consistency: enforced\n"
        "  matter_scope: enforced\n"
        "  upl_check: required\n"
        "  disclaimer: legal-research-only\n"
        "---\n\n"
        "# statute-compare\n\nCompare provisions.\n",
        encoding="utf-8",
    )
    (prompts / "system.md").write_text(
        "You are a careful legal-research assistant.\nFocus on citations.\n",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def evolve_db(postgresql):
    """Fresh Postgres per test with Phase 2A DDL applied.

    Yields a psycopg connection. Test runs as the DB owner (superuser-equivalent
    in pytest-postgresql), NOT as kairos_evolve_api — that role exists but is
    referenced via SET LOCAL ROLE in routing_store tests that explicitly want to
    verify role-level grant behavior.
    """
    ddl_path = Path(__file__).resolve().parent / "sql" / "ddl_phase2a.sql"
    with postgresql.cursor() as cur:
        cur.execute(ddl_path.read_text())
    postgresql.commit()
    yield postgresql
