"""WS02: HTTP-layer tests for the new /wo-carbon/calculate endpoint.

tests/test_wo_carbon_golden.py already proves the ENGINE (calculate_from_
work_order) matches the golden baselines. This file proves the new HTTP
wrapper around it -- temp-file handling, multipart form parsing, paired
floor_area_sqm/floor_area_basis validation, response-model serialization
-- doesn't change any of those numbers, plus that the validation error
paths actually fire. Reuses the same golden files and scalar-field list
as the engine-level test rather than inventing a second set of expected
numbers.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.golden_utils import diff_result, load_golden, source_file_exists

client = TestClient(app)

WO_SCALAR_FIELDS = [
    "n_line_items_parsed",
    "n_line_items_computed",
    "total_gwp_kg_co2e",
    "total_gwp_tonnes_co2e",
    "gwp_per_sqm",
    "parse_checksum_ok",
]

# name -> (floor_area_sqm, floor_area_basis), matching
# scripts/generate_golden_files.py's DOCUMENTS / test_wo_carbon_golden.py.
_CASES = {
    "ecopolitan_wo": (205981.65, "built_up_total"),
    "botanico_wo": (166022.98, "built_up_total"),
}


@pytest.mark.parametrize("name", sorted(_CASES))
def test_wo_carbon_api_matches_golden(name: str):
    golden = load_golden(name)

    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)

    source_path = golden["_meta"]["source_path"]
    floor_area_sqm, floor_area_basis = _CASES[name]

    with open(source_path, "rb") as f:
        resp = client.post(
            "/wo-carbon/calculate",
            files={"wo_file": (source_path.split("/")[-1], f, "application/pdf")},
            data={"floor_area_sqm": floor_area_sqm, "floor_area_basis": floor_area_basis},
        )

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text[:500]}"
    body = resp.json()

    current = {
        "n_line_items_parsed": body["n_line_items_parsed"],
        "n_line_items_computed": body["n_line_items_computed"],
        "total_gwp_kg_co2e": body["total_gwp_kg_co2e"],
        "total_gwp_tonnes_co2e": body["total_gwp_tonnes_co2e"],
        "gwp_per_sqm": body["gwp_per_sqm"],
        "parse_checksum_ok": body["parse_checksum_ok"],
        "by_category": [
            {"category": c["category"], "gwp_kg_co2e": c["gwp_kg_co2e"], "line_item_count": c["line_item_count"]}
            for c in body["by_category"]
        ],
    }

    diffs = diff_result(golden, current, WO_SCALAR_FIELDS)
    assert not diffs, (
        f"/wo-carbon/calculate response for {name!r} no longer matches tests/golden/{name}.json "
        f"({len(diffs)} difference(s)):\n  " + "\n  ".join(diffs)
    )


def test_wo_carbon_api_rejects_non_pdf():
    resp = client.post(
        "/wo-carbon/calculate",
        files={"wo_file": ("not_a_wo.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


# A minimal, valid, single blank page -- no text layer at all -- standing
# in for a scanned/image-only Work Order PDF (WS03: pdfplumber can open
# it without error, it just finds nothing to extract; that's the case
# this constant exercises, not the "not a PDF at all" case above).
_BLANK_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n0\n%%EOF"
)


def test_wo_carbon_api_rejects_pdf_with_no_extractable_text():
    resp = client.post(
        "/wo-carbon/calculate",
        files={"wo_file": ("scanned.pdf", _BLANK_PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 422
    assert "scanned" in resp.json()["detail"].lower()


def test_wo_carbon_api_rejects_unpaired_floor_area():
    golden = load_golden("ecopolitan_wo")
    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)

    with open(golden["_meta"]["source_path"], "rb") as f:
        resp = client.post(
            "/wo-carbon/calculate",
            files={"wo_file": ("wo.pdf", f, "application/pdf")},
            # floor_area_sqm given without floor_area_basis -- must be rejected,
            # not silently computed with an undefined area basis.
            data={"floor_area_sqm": "100000"},
        )
    assert resp.status_code == 400
    assert "together" in resp.json()["detail"].lower()