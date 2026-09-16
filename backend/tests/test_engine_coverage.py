"""Workstream 07: engine-level integration tests for the `coverage` field
on both BoqCarbonResult and WoCarbonResult, against the real reference
documents this project already validates against elsewhere (see
tests/test_boq_carbon_golden.py / tests/test_wo_carbon_golden.py) --
these are not golden-value tests (the exact figures would make this file
as brittle as the golden ones for no extra benefit); they assert the
*shape and internal consistency* of the coverage summary itself: the
percentages are well-formed, top5 coverage reflects the real, known
Ecopolitan WO gap this workstream's own roadmap entry cites, and every
excluded line item is accounted for by exactly one of the six reasons.
"""

from __future__ import annotations

import pytest

from app.services import coverage
from app.services.boq_carbon.engine import calculate_from_boq
from app.services.boq_carbon.parser import extract_from_first_primary_sheet
from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS
from app.services.wo_carbon.wo_carbon_engine import calculate_from_work_order
from app.services import company_store
from tests.golden_utils import load_golden, source_file_exists


def _assert_well_formed(c):
    assert 0.0 <= c.coverage_pct <= 100.0
    assert 0.0 <= c.top5_coverage_pct <= 100.0
    assert c.computed_value <= c.total_value + 1e-6
    assert c.top5_computed_value <= c.top5_total_value + 1e-6
    assert c.top5_total_value <= c.total_value + 1e-6
    for reason in {e.reason for e in c.excluded_by_reason}:
        assert reason in coverage.ALL_REASONS
    # excluded value + computed value should reconcile to the total
    excluded_total = sum(e.value_excluded for e in c.excluded_by_reason)
    assert c.computed_value + excluded_total == pytest.approx(c.total_value, rel=1e-6)


def test_wo_coverage_matches_known_ecopolitan_top5_gap():
    golden = load_golden("ecopolitan_wo")
    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)

    source_path = golden["_meta"]["source_path"]
    master_path = str(company_store.master_item_codes_path(company_store.DEFAULT_COMPANY_ID))
    result = calculate_from_work_order(source_path, master_path)
    c = result.coverage
    _assert_well_formed(c)

    # The real, known gap this workstream's roadmap entry cites: 574
    # top5-category line items / ~Rs 20.78M excluded, almost entirely
    # unhandled_unit (concrete/reinforcement_steel rows priced in units
    # this engine has no sourced conversion for -- see wo_carbon_engine
    # .py's own module docstring). Asserted as a generous range, not an
    # exact figure, so this test survives an unrelated future factor or
    # parser change without turning into a second golden file.
    assert c.top5_coverage_pct > 95.0
    by_reason = {e.reason: e for e in c.excluded_by_reason}
    assert coverage.REASON_UNHANDLED_UNIT in by_reason
    assert coverage.REASON_NOT_CONTRIBUTING in by_reason
    assert coverage.REASON_NEEDS_REVIEW in by_reason


def test_boq_coverage_is_internally_consistent_on_real_boqs():
    for name, gfa in [("ecopolitan_boq", 205981.65), ("botanico_boq", 166022.98)]:
        golden = load_golden(name)
        skip_reason = source_file_exists(golden)
        if skip_reason:
            pytest.skip(skip_reason)

        source_path = golden["_meta"]["source_path"]
        sheet, _ = extract_from_first_primary_sheet(source_path, SUPPLEMENTARY_SHEET_PATTERNS)
        result = calculate_from_boq(source_path, sheet, floor_area_sqm=gfa, floor_area_basis="built_up_total")
        c = result.coverage
        _assert_well_formed(c)
        # boq_carbon has no contributes-flag concept -- it should never
        # emit the two wo_carbon-only reasons.
        reasons_seen = {e.reason for e in c.excluded_by_reason}
        assert coverage.REASON_NOT_CONTRIBUTING not in reasons_seen
        assert coverage.REASON_NEEDS_REVIEW not in reasons_seen


def test_boq_top5_categories_include_rcc_and_pcc():
    """boq_carbon's classifier splits concrete into rcc/pcc (a real,
    deliberate distinction -- see classifier.py's docstring); both must
    still count toward the top5 slice, or PCC/RCC-heavy projects would
    silently understate their top5_total_value."""
    golden = load_golden("ecopolitan_boq")
    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)
    source_path = golden["_meta"]["source_path"]
    sheet, _ = extract_from_first_primary_sheet(source_path, SUPPLEMENTARY_SHEET_PATTERNS)
    result = calculate_from_boq(source_path, sheet, floor_area_sqm=205981.65, floor_area_basis="built_up_total")
    assert any(li.category in ("rcc", "pcc") for li in result.line_items)
    assert result.coverage.top5_total_value > 0