"""Golden-file regression tests for the wo_carbon pipeline (Workstream 00).

Covers both reference Work Orders. ecopolitan_wo's source PDF is present
in a normal checkout of this repo and runs for real every time. botanico_wo
is special: its source PDF has not yet been supplied (see tests/golden/
botanico_wo.json's _meta), so this test SKIPS it with an explanatory
reason rather than failing OR silently passing -- the moment the real PDF
is placed at app/data/work_orders/Provident Botanico_WO_SICL.pdf, this
same test starts running it for real, comparing against the numbers
originally captured from the user's own terminal output.
"""

from __future__ import annotations

import pytest

from app.services import company_store
from app.services.wo_carbon.wo_carbon_engine import calculate_from_work_order
from tests.golden_utils import diff_result, load_golden, source_file_exists

WO_SCALAR_FIELDS = [
    "n_line_items_parsed",
    "n_line_items_computed",
    "total_gwp_kg_co2e",
    "total_gwp_tonnes_co2e",
    "gwp_per_sqm",
    "parse_checksum_ok",
]

# Workstream 04: moved from a single global file to per-company storage.
# Both reference Work Orders are Provident's own, so this always resolves
# to company_store.DEFAULT_COMPANY_ID's dataset.
MASTER_JSON_PATH = str(company_store.master_item_codes_path(company_store.DEFAULT_COMPANY_ID))

# name -> floor_area_sqm, matching scripts/generate_golden_files.py's DOCUMENTS
_CASES = {
    "ecopolitan_wo": 205981.65,
    "botanico_wo": 166022.98,
}


@pytest.mark.parametrize("name", sorted(_CASES))
def test_wo_carbon_matches_golden(name: str):
    golden = load_golden(name)

    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)

    source_path = golden["_meta"]["source_path"]
    floor_area_sqm = _CASES[name]

    result = calculate_from_work_order(
        source_path, MASTER_JSON_PATH, floor_area_sqm=floor_area_sqm, floor_area_basis="built_up_total"
    )

    current = {
        "n_line_items_parsed": result.n_line_items_parsed,
        "n_line_items_computed": result.n_line_items_computed,
        "total_gwp_kg_co2e": result.total_gwp_kg_co2e,
        "total_gwp_tonnes_co2e": result.total_gwp_tonnes_co2e,
        "gwp_per_sqm": result.gwp_per_sqm,
        "parse_checksum_ok": result.parse_checksum_ok,
        "by_category": [
            {"category": c.category, "gwp_kg_co2e": c.gwp_kg_co2e, "line_item_count": c.line_item_count}
            for c in result.by_category
        ],
    }

    diffs = diff_result(golden, current, WO_SCALAR_FIELDS)
    assert not diffs, (
        f"wo_carbon output for {name!r} no longer matches tests/golden/{name}.json "
        f"({len(diffs)} difference(s)):\n  " + "\n  ".join(diffs) +
        f"\n\nIf this change is intentional, regenerate with:\n"
        f"  python scripts/generate_golden_files.py --write --note \"why this changed\" --only {name}"
    )