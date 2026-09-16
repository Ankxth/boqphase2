"""Workstream 07: unit tests for the shared coverage/honesty-reporting
layer (app.services.coverage), independent of either carbon engine --
see that module's own docstring for the design. Engine-level integration
is covered separately by tests/test_engine_coverage.py (real reference
documents) and by the coverage numbers already asserted implicitly via
the golden-file tests (n_lines_computed etc).
"""

from __future__ import annotations

import pytest

from app.services import coverage


def _row(value, computed, is_top5=False, reason=None):
    return {"value": value, "computed": computed, "is_top5": is_top5, "reason": reason}


def test_all_computed_gives_100pct_coverage_and_no_exclusions():
    rows = [_row(100.0, True), _row(200.0, True)]
    c = coverage.build_coverage(rows)
    assert c.total_value == pytest.approx(300.0)
    assert c.computed_value == pytest.approx(300.0)
    assert c.coverage_pct == pytest.approx(100.0)
    assert c.excluded_by_reason == []


def test_mixed_rows_compute_correct_pct_and_bucket_exclusions_by_reason():
    rows = [
        _row(100.0, True),
        _row(50.0, False, reason=coverage.REASON_UNHANDLED_UNIT),
        _row(30.0, False, reason=coverage.REASON_UNHANDLED_UNIT),
        _row(20.0, False, reason=coverage.REASON_UNCLASSIFIED),
    ]
    c = coverage.build_coverage(rows)
    assert c.total_value == pytest.approx(200.0)
    assert c.computed_value == pytest.approx(100.0)
    assert c.coverage_pct == pytest.approx(50.0)
    by_reason = {e.reason: e for e in c.excluded_by_reason}
    assert by_reason[coverage.REASON_UNHANDLED_UNIT].line_item_count == 2
    assert by_reason[coverage.REASON_UNHANDLED_UNIT].value_excluded == pytest.approx(80.0)
    assert by_reason[coverage.REASON_UNCLASSIFIED].line_item_count == 1
    assert by_reason[coverage.REASON_UNCLASSIFIED].value_excluded == pytest.approx(20.0)
    # Sorted by value descending -- the bigger gap listed first.
    assert c.excluded_by_reason[0].reason == coverage.REASON_UNHANDLED_UNIT


def test_top5_slice_is_independent_of_overall_coverage():
    """Overall coverage can look fine while the top5 (highest-impact)
    slice still has a real gap -- the whole reason this field exists
    (see the roadmap's WS07 entry: 574 top5 line items / ~Rs 20.78M were
    excluded on a real WO even though overall coverage looked fine)."""
    rows = [
        _row(900.0, True, is_top5=False),  # plenty of non-top5 value, all computed
        _row(50.0, True, is_top5=True),
        _row(50.0, False, is_top5=True, reason=coverage.REASON_UNHANDLED_UNIT),
    ]
    c = coverage.build_coverage(rows)
    assert c.coverage_pct == pytest.approx(95.0)  # looks fine overall
    assert c.top5_total_value == pytest.approx(100.0)
    assert c.top5_computed_value == pytest.approx(50.0)
    assert c.top5_coverage_pct == pytest.approx(50.0)  # but the top5 slice is only half covered


def test_reason_defaults_to_unclassified_when_missing():
    rows = [_row(10.0, False, reason=None)]
    c = coverage.build_coverage(rows)
    assert c.excluded_by_reason[0].reason == coverage.REASON_UNCLASSIFIED


def test_empty_rows_gives_zero_pct_not_a_crash():
    c = coverage.build_coverage([])
    assert c.total_value == 0.0
    assert c.coverage_pct == 0.0
    assert c.top5_coverage_pct == 0.0
    assert c.excluded_by_reason == []


def test_all_reasons_are_distinct_and_exported():
    assert len(coverage.ALL_REASONS) == len(set(coverage.ALL_REASONS)) == 6


def test_top5_material_categories_are_the_five_named_in_user_facing_copy():
    assert coverage.TOP5_MATERIAL_CATEGORIES == {
        "concrete", "reinforcement_steel", "structural_steel", "aluminium", "glass",
    }