"""Workstream 06: tests for /wo-carbon/calculate's opt-in auto-
registration -- metadata-only (no quantity-extraction cache), see that
endpoint's own module docstring for why. Uses the real Ecopolitan Work
Order PDF this project already validates against elsewhere.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import boq_cache, company_store, reference_store
from tests.golden_utils import load_golden, source_file_exists

client = TestClient(app)

# Computed at module-import time, BEFORE any test's isolated_company_storage
# fixture monkeypatches company_store.COMPANIES_DIR -- same pattern
# tests/test_wo_carbon_golden.py already uses. These registration tests
# care about the registration side effect for a NEW company ("acme"),
# which has no master_item_codes.json of its own in the isolated
# tmp_path; passing this real path as an explicit override (same
# override param /wo-carbon/calculate already supports for testing) lets
# the WO actually parse and compute, without which the endpoint 500s
# before registration logic is ever reached.
REAL_MASTER_JSON_PATH = str(company_store.master_item_codes_path(company_store.DEFAULT_COMPANY_ID))


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def _ecopolitan_wo_path():
    golden = load_golden("ecopolitan_wo")
    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)
    return golden["_meta"]["source_path"], 205981.65


def test_register_as_reference_writes_metadata_only_no_extraction_cache():
    source_path, gfa = _ecopolitan_wo_path()
    with open(source_path, "rb") as f:
        resp = client.post(
            "/wo-carbon/calculate",
            files={"wo_file": (source_path.split("/")[-1], f, "application/pdf")},
            data={
                "floor_area_sqm": gfa, "floor_area_basis": "built_up_total",
                "register_as_reference": "true", "company_id": "acme",
                "structural_system_type": "rcc_frame", "typology": "residential",
                "reference_slug": "acme_wo_tower", "master_json_path": REAL_MASTER_JSON_PATH,
            },
        )
    assert resp.status_code == 200, resp.text[:500]
    body = resp.json()
    assert body["registered_as_reference"] is True
    assert body["reference_slug"] == "acme_wo_tower"
    assert "metadata only" in body["registration_note"].lower()

    meta = reference_store.get_metadata("acme_wo_tower", company_id="acme")
    assert meta is not None
    assert meta["gfa_sqm"] == gfa

    # The deliberate limitation: no cached extraction for a WO-sourced reference.
    assert boq_cache.load_extraction("acme_wo_tower", company_id="acme") is None

    # Still counts toward the company's history / GFA-ranked matching even
    # without an extraction (see company_history.py + find_candidates).
    refs = reference_store.list_references(company_id="acme")
    assert any(r["slug"] == "acme_wo_tower" and not r["usable_for_matching"] for r in refs)


def test_register_as_reference_requires_structural_system_and_typology():
    source_path, gfa = _ecopolitan_wo_path()
    with open(source_path, "rb") as f:
        resp = client.post(
            "/wo-carbon/calculate",
            files={"wo_file": (source_path.split("/")[-1], f, "application/pdf")},
            data={"floor_area_sqm": gfa, "floor_area_basis": "built_up_total", "register_as_reference": "true", "master_json_path": REAL_MASTER_JSON_PATH},
        )
    assert resp.status_code == 400
    assert "structural_system_type" in resp.json()["detail"]


def test_default_behavior_unchanged_when_register_as_reference_omitted():
    source_path, gfa = _ecopolitan_wo_path()
    with open(source_path, "rb") as f:
        resp = client.post(
            "/wo-carbon/calculate",
            files={"wo_file": (source_path.split("/")[-1], f, "application/pdf")},
            data={"floor_area_sqm": gfa, "floor_area_basis": "built_up_total", "master_json_path": REAL_MASTER_JSON_PATH},
        )
    assert resp.status_code == 200
    assert resp.json()["registered_as_reference"] is False