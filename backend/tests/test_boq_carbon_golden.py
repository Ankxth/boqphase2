"""Golden-file regression tests for the boq_carbon pipeline (Workstream 00).

Runs calculate_from_boq() for real against the two reference BOQ Excel
files this project has been validated against by hand throughout (see
tests/golden/*.json and scripts/generate_golden_files.py), and asserts
the full result -- scalar fields AND the complete by-category breakdown
-- matches the committed baseline within a small relative float
tolerance. See tests/golden_utils.py's module docstring for why the
comparison is structured this way.

A failure here means the pipeline's output actually changed. That is
not necessarily wrong -- Workstream 01 (unifying the emission-factor
source) is expected to deliberately change some of these numbers -- but
it must always be a deliberate, reviewed change: read the printed diff,
decide whether it's intended, and if so regenerate the golden file with
`python scripts/generate_golden_files.py --write --note "why"` rather
than assuming the test itself is stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.boq_carbon.engine import calculate_from_boq
from app.services.boq_carbon.parser import extract_from_first_primary_sheet
from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS
from tests.golden_utils import diff_result, load_golden, source_file_exists

BOQ_SCALAR_FIELDS = [
    "n_lines_total",
    "n_lines_classified",
    "n_lines_computed",
    "total_gwp_kg_co2e",
    "total_gwp_tonnes_co2e",
    "gwp_per_sqm",
]

# name -> floor_area_sqm, matching scripts/generate_golden_files.py's DOCUMENTS
_CASES = {
    "ecopolitan_boq": 205981.65,
    "botanico_boq": 166022.98,
}


@pytest.mark.parametrize("name", sorted(_CASES))
def test_boq_carbon_matches_golden(name: str):
    golden = load_golden(name)

    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)

    source_path = golden["_meta"]["source_path"]
    floor_area_sqm = _CASES[name]

    sheet, _ = extract_from_first_primary_sheet(source_path, SUPPLEMENTARY_SHEET_PATTERNS)
    result = calculate_from_boq(
        source_path, sheet, floor_area_sqm=floor_area_sqm, floor_area_basis="built_up_total"
    )

    current = {
        "n_lines_total": result.n_lines_total,
        "n_lines_classified": result.n_lines_classified,
        "n_lines_computed": result.n_lines_computed,
        "total_gwp_kg_co2e": result.total_gwp_kg_co2e,
        "total_gwp_tonnes_co2e": result.total_gwp_tonnes_co2e,
        "gwp_per_sqm": result.gwp_per_sqm,
        "by_category": [
            {"category": c.category, "gwp_kg_co2e": c.gwp_kg_co2e, "line_item_count": c.line_item_count}
            for c in result.by_category
        ],
    }

    diffs = diff_result(golden, current, BOQ_SCALAR_FIELDS)
    assert not diffs, (
        f"boq_carbon output for {name!r} no longer matches tests/golden/{name}.json "
        f"({len(diffs)} difference(s)):\n  " + "\n  ".join(diffs) +
        f"\n\nIf this change is intentional, regenerate with:\n"
        f"  python scripts/generate_golden_files.py --write --note \"why this changed\" --only {name}"
    )