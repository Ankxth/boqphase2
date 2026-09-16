"""Workstream 06: tests for /boq-carbon/calculate's opt-in auto-
registration (register_as_reference=True), using the real reference BOQ
files this project already validates against elsewhere (see
tests/test_boq_carbon_golden.py) rather than a synthetic file -- the
thing under test here is the registration side effect (metadata +
cached extraction written for the right company, nothing written when
not asked for), not the carbon numbers themselves, which the golden
tests already cover.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import boq_cache, company_store, reference_store
from tests.golden_utils import load_golden, source_file_exists

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def _ecopolitan_boq_path():
    golden = load_golden("ecopolitan_boq")
    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)
    return golden["_meta"]["source_path"], 205981.65


def test_default_behavior_unchanged_when_register_as_reference_omitted():
    source_path, gfa = _ecopolitan_boq_path()
    with open(source_path, "rb") as f:
        resp = client.post(
            "/boq-carbon/calculate",
            files={"boq_file": (source_path.split("/")[-1], f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"floor_area_sqm": gfa, "floor_area_basis": "built_up_total"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["registered_as_reference"] is False
    assert body["reference_slug"] is None
    assert reference_store.list_references("provident") == []


def test_register_as_reference_requires_structural_system_and_typology():
    source_path, gfa = _ecopolitan_boq_path()
    with open(source_path, "rb") as f:
        resp = client.post(
            "/boq-carbon/calculate",
            files={"boq_file": (source_path.split("/")[-1], f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"floor_area_sqm": gfa, "floor_area_basis": "built_up_total", "register_as_reference": "true"},
        )
    assert resp.status_code == 400
    assert "structural_system_type" in resp.json()["detail"]


def test_register_as_reference_writes_metadata_and_extraction():
    source_path, gfa = _ecopolitan_boq_path()
    with open(source_path, "rb") as f:
        resp = client.post(
            "/boq-carbon/calculate",
            files={"boq_file": (source_path.split("/")[-1], f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={
                "floor_area_sqm": gfa, "floor_area_basis": "built_up_total",
                "register_as_reference": "true", "company_id": "acme",
                "structural_system_type": "rcc_frame", "typology": "residential",
                "reference_slug": "acme_test_tower", "use_llm_extraction_fallback": "false",
            },
        )
    assert resp.status_code == 200, resp.text[:500]
    body = resp.json()
    assert body["registered_as_reference"] is True
    assert body["reference_slug"] == "acme_test_tower"
    assert body["registration_note"]

    meta = reference_store.get_metadata("acme_test_tower", company_id="acme")
    assert meta is not None
    assert meta["structural_system_type"] == "rcc_frame"
    assert meta["typology"] == "residential"
    assert meta["gfa_sqm"] == gfa

    extraction = boq_cache.load_extraction("acme_test_tower", company_id="acme")
    assert extraction is not None
    assert "materials" in extraction
    assert "rcc" in extraction["materials"] or "reinforcement_steel" in extraction["materials"]

    # Isolation: not visible under a different company_id / the default company.
    assert reference_store.get_metadata("acme_test_tower", company_id="provident") is None

    # Immediately usable_for_matching (no separate "activate" step).
    candidates = reference_store.find_candidates(structural_system_type="rcc_frame", target_gfa_sqm=gfa, company_id="acme")
    assert any(c["slug"] == "acme_test_tower" for c in candidates)


def test_reference_slug_defaults_from_filename_when_omitted():
    source_path, gfa = _ecopolitan_boq_path()
    with open(source_path, "rb") as f:
        resp = client.post(
            "/boq-carbon/calculate",
            files={"boq_file": ("My Test BOQ v2.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={
                "floor_area_sqm": gfa, "floor_area_basis": "built_up_total",
                "register_as_reference": "true", "company_id": "acme",
                "structural_system_type": "rcc_frame", "typology": "residential",
                "use_llm_extraction_fallback": "false",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["reference_slug"] == "my_test_boq_v2"