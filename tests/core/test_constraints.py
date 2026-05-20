"""constraint gate tests — universal + skill artifact validators."""

from __future__ import annotations

from kairos_evolve.core.constraints import (
    ConstraintReport,
    check_growth_limit,
    check_no_secret_pattern,
    check_non_empty,
    check_safety_block_intact,
    check_size_limit,
    check_skill_frontmatter_valid,
    check_utf8_clean,
    run_skill_artifact_gates,
    run_universal_artifact_gates,
)


def test_non_empty_passes_for_non_empty():
    assert check_non_empty("hello").passed


def test_non_empty_fails_for_empty():
    r = check_non_empty("")
    assert not r.passed
    assert "empty" in r.message.lower()


def test_size_limit_pass():
    assert check_size_limit("a" * 100, limit=200).passed


def test_size_limit_fail():
    r = check_size_limit("a" * 300, limit=200)
    assert not r.passed
    assert "300" in r.message and "200" in r.message


def test_growth_limit_pass():
    r = check_growth_limit("a" * 110, baseline="a" * 100, max_growth=0.2)
    assert r.passed


def test_growth_limit_fail():
    r = check_growth_limit("a" * 200, baseline="a" * 100, max_growth=0.2)
    assert not r.passed


def test_utf8_clean_pass():
    assert check_utf8_clean("normal text").passed


def test_utf8_clean_rejects_control_chars():
    r = check_utf8_clean("text\x01bad")
    assert not r.passed


def test_no_secret_pattern_pass():
    assert check_no_secret_pattern("just some prose about §301").passed


def test_no_secret_pattern_rejects_anthropic_key():
    r = check_no_secret_pattern("config: sk-ant-api03-secret-blob-here-fakeXYZ")
    assert not r.passed
    assert "secret" in r.message.lower()


def test_skill_frontmatter_valid_pass():
    body = (
        "---\nname: x\ndescription: hi\nversion: 0.1.0\nrisk_tier: low\n"
        "safety:\n  citation_verification: required\n"
        "  jurisdiction_consistency: enforced\n  matter_scope: enforced\n"
        "  upl_check: required\n  disclaimer: legal-research-only\n---\nbody"
    )
    assert check_skill_frontmatter_valid(body).passed


def test_skill_frontmatter_invalid_no_yaml():
    assert not check_skill_frontmatter_valid("no frontmatter here").passed


def test_safety_block_intact_pass():
    baseline_fm = {
        "safety": {
            "citation_verification": "required",
            "jurisdiction_consistency": "enforced",
            "matter_scope": "enforced",
            "upl_check": "required",
            "disclaimer": "legal-research-only",
        },
        "risk_tier": "medium",
    }
    candidate_fm = dict(baseline_fm)
    assert check_safety_block_intact(candidate_fm, baseline=baseline_fm).passed


def test_safety_block_weakening_rejected():
    baseline_fm = {
        "safety": {
            "citation_verification": "required",
            "jurisdiction_consistency": "enforced",
            "matter_scope": "enforced",
            "upl_check": "required",
            "disclaimer": "legal-research-only",
        },
        "risk_tier": "medium",
    }
    candidate_fm = {
        "safety": {
            **baseline_fm["safety"],
            "citation_verification": "advisory",
        },
        "risk_tier": "medium",
    }
    r = check_safety_block_intact(candidate_fm, baseline=baseline_fm)
    assert not r.passed
    assert "citation_verification" in r.message


def test_safety_block_risk_tier_lowering_rejected():
    baseline_fm = {"safety": {}, "risk_tier": "high"}
    candidate_fm = {"safety": {}, "risk_tier": "medium"}
    r = check_safety_block_intact(candidate_fm, baseline=baseline_fm)
    assert not r.passed
    assert "risk_tier" in r.message


def test_run_universal_artifact_gates_aggregates():
    report = run_universal_artifact_gates(
        artifact="hello world extended with more content",
        size_limit=1000,
        baseline="hello world extended with more content",
    )
    assert isinstance(report, ConstraintReport)
    assert len(report.passed) >= 4
    assert report.all_passed()


def test_run_skill_artifact_gates_full_pass(fake_kairos_repo):
    from kairos_evolve.core.skill_io import find_skill, load_skill

    skill = load_skill(find_skill("statute-compare", kairos_repo=fake_kairos_repo))
    import yaml

    candidate_body = (
        "---\n" + yaml.safe_dump(skill.frontmatter, sort_keys=False) + "---\n" + skill.body
    )
    report = run_skill_artifact_gates(
        artifact=candidate_body,
        size_limit=10000,
        baseline=candidate_body,
        baseline_frontmatter=skill.frontmatter,
    )
    assert report.all_passed(), report.failed
