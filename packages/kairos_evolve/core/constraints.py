"""Pass/fail constraint gates for evolve artifacts.

Three-tier taxonomy from kairos-evolve design spec §6.1:
  - universal artifact gates (every phase)
  - skill artifact gates (L1, L2, L4, L5 — touches SKILL.md)
  - routing-policy gates (L3 only; not in Phase 1)

Each gate is a pure function returning a ConstraintResult. The aggregate
runners take an artifact and return a ConstraintReport.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

_SECRET_PATTERNS = re.compile(
    r"("
    r"sk-ant-api\S+"
    r"|sk-or-v1-\S+"
    r"|sk-\S{20,}"
    r"|ghp_\S+"
    r"|ghu_\S+"
    r"|xoxb-\S+"
    r"|xapp-\S+"
    r"|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN\s+(RSA\s+)?PRIVATE\sKEY-----"
    r")"
)

_SAFETY_KEYS_FORBIDDEN_WEAKENING = {
    "citation_verification": {
        "required": {"advisory", "disabled", "not-applicable"},
        "advisory": {"disabled", "not-applicable"},
    },
    "jurisdiction_consistency": {
        "enforced": {"advisory", "disabled", "not-applicable"},
        "advisory": {"disabled", "not-applicable"},
    },
    "matter_scope": {
        "enforced": {"advisory", "disabled", "not-applicable"},
        "advisory": {"disabled", "not-applicable"},
    },
    "upl_check": {"required": {"not-applicable"}},  # already correct
}

_RISK_TIER_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class ConstraintResult:
    name: str
    passed: bool
    message: str


@dataclass
class ConstraintReport:
    passed: list[ConstraintResult] = field(default_factory=list)
    failed: list[ConstraintResult] = field(default_factory=list)
    not_applicable: list[ConstraintResult] = field(default_factory=list)

    def add(self, r: ConstraintResult) -> None:
        (self.passed if r.passed else self.failed).append(r)

    def all_passed(self) -> bool:
        return not self.failed


def check_non_empty(artifact: str) -> ConstraintResult:
    if artifact.strip():
        return ConstraintResult("non_empty", True, "non-empty")
    return ConstraintResult("non_empty", False, "artifact is empty")


def check_size_limit(artifact: str, *, limit: int) -> ConstraintResult:
    size = len(artifact.encode("utf-8"))
    if size <= limit:
        return ConstraintResult("size_limit", True, f"{size}/{limit} bytes")
    return ConstraintResult("size_limit", False, f"{size} > {limit} bytes")


def check_growth_limit(
    artifact: str, *, baseline: str, max_growth: float = 0.5
) -> ConstraintResult:
    base_size = max(1, len(baseline.encode("utf-8")))
    grew = (len(artifact.encode("utf-8")) - base_size) / base_size
    if grew <= max_growth:
        return ConstraintResult("growth_limit", True, f"grew {grew:+.2%} (<= {max_growth:+.2%})")
    return ConstraintResult("growth_limit", False, f"grew {grew:+.2%} > {max_growth:+.2%}")


def check_utf8_clean(artifact: str) -> ConstraintResult:
    try:
        artifact.encode("utf-8").decode("utf-8")
    except UnicodeError as e:
        return ConstraintResult("utf8_clean", False, f"utf-8 decode error: {e}")
    for ch in artifact:
        if ch in ("\n", "\r", "\t"):
            continue
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            return ConstraintResult("utf8_clean", False, f"control char U+{ord(ch):04x}")
    return ConstraintResult("utf8_clean", True, "utf-8 + printable")


def check_no_secret_pattern(artifact: str) -> ConstraintResult:
    m = _SECRET_PATTERNS.search(artifact)
    if m is None:
        return ConstraintResult("no_secret_pattern", True, "no secrets detected")
    return ConstraintResult(
        "no_secret_pattern", False, f"possible secret matched: {m.group(0)[:32]}..."
    )


def check_skill_frontmatter_valid(artifact: str) -> ConstraintResult:
    if not artifact.strip().startswith("---"):
        return ConstraintResult("valid_frontmatter", False, "missing YAML frontmatter")
    head, sep, _ = artifact.partition("\n---\n")
    if not sep:
        return ConstraintResult("valid_frontmatter", False, "frontmatter not terminated")
    try:
        fm = yaml.safe_load(head[4:])
    except yaml.YAMLError as e:
        return ConstraintResult("valid_frontmatter", False, f"YAML parse error: {e}")
    if not isinstance(fm, dict):
        return ConstraintResult("valid_frontmatter", False, "frontmatter is not a mapping")
    return ConstraintResult("valid_frontmatter", True, "YAML frontmatter parses")


def check_safety_block_intact(
    candidate_frontmatter: dict[str, Any],
    *,
    baseline: dict[str, Any],
) -> ConstraintResult:
    """Reject if candidate weakens any safety key or lowers risk_tier."""
    c_safety = candidate_frontmatter.get("safety", {}) or {}
    b_safety = baseline.get("safety", {}) or {}

    for key, weakenings in _SAFETY_KEYS_FORBIDDEN_WEAKENING.items():
        c_val = c_safety.get(key)
        b_val = b_safety.get(key)
        if b_val and c_val and c_val != b_val:
            forbidden = weakenings.get(b_val, set())
            if c_val in forbidden:
                return ConstraintResult(
                    "safety_block_intact",
                    False,
                    f"weakening {key}: {b_val!r} -> {c_val!r}",
                )

    c_disc = (c_safety.get("disclaimer") or "").strip()
    b_disc = (b_safety.get("disclaimer") or "").strip()
    if b_disc and not c_disc:
        return ConstraintResult("safety_block_intact", False, "disclaimer removed or emptied")

    c_rt = candidate_frontmatter.get("risk_tier")
    b_rt = baseline.get("risk_tier")
    if c_rt and b_rt and _RISK_TIER_RANK.get(c_rt, -1) < _RISK_TIER_RANK.get(b_rt, -1):
        return ConstraintResult(
            "risk_tier_never_lowers",
            False,
            f"risk_tier lowered: {b_rt!r} -> {c_rt!r}",
        )

    return ConstraintResult("safety_block_intact", True, "safety block preserved")


def run_universal_artifact_gates(
    *, artifact: str, size_limit: int, baseline: str
) -> ConstraintReport:
    report = ConstraintReport()
    for r in (
        check_non_empty(artifact),
        check_size_limit(artifact, limit=size_limit),
        check_growth_limit(artifact, baseline=baseline),
        check_utf8_clean(artifact),
        check_no_secret_pattern(artifact),
    ):
        report.add(r)
    return report


def run_skill_artifact_gates(
    *,
    artifact: str,
    size_limit: int,
    baseline: str,
    baseline_frontmatter: dict[str, Any],
) -> ConstraintReport:
    """Universal + skill-specific gates."""
    report = run_universal_artifact_gates(
        artifact=artifact, size_limit=size_limit, baseline=baseline
    )
    fm_check = check_skill_frontmatter_valid(artifact)
    report.add(fm_check)
    if fm_check.passed:
        head, _, _ = artifact.partition("\n---\n")
        candidate_fm = yaml.safe_load(head[4:]) or {}
        report.add(check_safety_block_intact(candidate_fm, baseline=baseline_frontmatter))
    return report


__all__ = [
    "ConstraintReport",
    "ConstraintResult",
    "check_growth_limit",
    "check_no_secret_pattern",
    "check_non_empty",
    "check_safety_block_intact",
    "check_size_limit",
    "check_skill_frontmatter_valid",
    "check_utf8_clean",
    "run_skill_artifact_gates",
    "run_universal_artifact_gates",
]
