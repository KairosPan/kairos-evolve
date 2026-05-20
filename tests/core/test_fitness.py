"""fitness module — protocol + pure helpers."""

from __future__ import annotations

import math

from kairos_evolve.core.fitness import (
    FitnessResult,
    keyword_overlap_score,
    length_penalty,
    weighted_composite,
)


def test_fitness_result_composite_default_weights():
    f = FitnessResult(correctness=1.0, procedure_following=1.0, conciseness=1.0)
    assert math.isclose(f.composite(), 1.0)


def test_fitness_result_composite_weighted():
    f = FitnessResult(correctness=1.0, procedure_following=0.0, conciseness=0.0)
    assert math.isclose(f.composite(), 0.5)


def test_fitness_result_with_length_penalty_subtracted():
    f = FitnessResult(correctness=1.0, procedure_following=1.0, conciseness=1.0, length_penalty=0.2)
    assert math.isclose(f.composite(), 0.8)


def test_keyword_overlap_empty_expected_returns_zero():
    assert keyword_overlap_score(expected="", actual="anything") == 0.0


def test_keyword_overlap_full_match():
    assert (
        keyword_overlap_score(
            expected="cite the controlling case",
            actual="be sure to cite the controlling case in your response",
        )
        == 1.0
    )


def test_keyword_overlap_partial():
    score = keyword_overlap_score(
        expected="cite controlling case",
        actual="cite the precedent",
    )
    assert math.isclose(score, 1 / 3)


def test_length_penalty_no_penalty_below_90pct():
    assert length_penalty(actual_size=80, max_size=100) == 0.0


def test_length_penalty_at_90pct_is_zero():
    assert math.isclose(length_penalty(actual_size=90, max_size=100), 0.0, abs_tol=1e-9)


def test_length_penalty_at_100pct_is_03():
    assert math.isclose(length_penalty(actual_size=100, max_size=100), 0.3, abs_tol=1e-9)


def test_length_penalty_clamped_at_03():
    assert length_penalty(actual_size=200, max_size=100) == 0.3


def test_weighted_composite_basic():
    assert math.isclose(weighted_composite({"a": 0.6, "b": 0.4}, weights={"a": 1.0, "b": 0.0}), 0.6)
