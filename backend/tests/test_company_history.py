"""Workstream 06: tests for app/services/company_history.py -- the
aggregation that feeds llm_fallback.py's company-anchored prompt.
"""

from __future__ import annotations

import pytest

from app.services import boq_cache, company_history, company_store, reference_store


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def test_empty_company_returns_zeroed_summary():
    result = company_history.historical_ranges("nobody_yet")
    assert result["n_reference_projects"] == 0
    assert result["gfa_sqm_range"] is None
    assert result["steel_reinforcement_ratio_kg_per_sqm"] is None
    assert result["concrete_vol_per_sqm"] is None


def _register(slug, gfa, structural, typology, steel_kg=None, rcc_cum=None, company_id="acme"):
    reference_store.upsert_metadata(slug, structural_system_type=structural, typology=typology, gfa_sqm=gfa, company_id=company_id)
    materials = {}
    if steel_kg is not None:
        materials["reinforcement_steel"] = {"deterministic": {"quantity": steel_kg, "unit": "kg"}}
    if rcc_cum is not None:
        materials["rcc"] = {"deterministic": {"quantity": rcc_cum}}
    if materials:
        boq_cache.save_extraction(slug, {"materials": materials}, company_id=company_id)


def test_aggregates_ratios_across_multiple_references():
    _register("proj_a", gfa=10000, structural="rcc_frame", typology="residential", steel_kg=650000, rcc_cum=4000)
    _register("proj_b", gfa=20000, structural="rcc_frame", typology="commercial", steel_kg=1500000, rcc_cum=9000)

    result = company_history.historical_ranges("acme")
    assert result["n_reference_projects"] == 2
    assert result["typology_counts"] == {"residential": 1, "commercial": 1}
    assert result["structural_system_type_counts"] == {"rcc_frame": 2}

    steel = result["steel_reinforcement_ratio_kg_per_sqm"]
    assert steel["n"] == 2
    assert steel["min"] == pytest.approx(65.0)   # 650000/10000
    assert steel["max"] == pytest.approx(75.0)   # 1500000/20000

    concrete = result["concrete_vol_per_sqm"]
    assert concrete["n"] == 2
    assert concrete["min"] == pytest.approx(0.4)  # 4000/10000
    assert concrete["max"] == pytest.approx(0.45)  # 9000/20000

    gfa_range = result["gfa_sqm_range"]
    assert gfa_range == {"min": 10000, "max": 20000, "avg": 15000, "n": 2}


def test_reference_without_extraction_still_counts_for_metadata_only():
    # A WO-sourced reference (Workstream 06's own metadata-only
    # registration in app/api/wo_carbon.py) has no cached extraction --
    # must still count toward n_reference_projects/typology/GFA, but
    # contribute nothing to the steel/concrete ratios.
    _register("wo_proj", gfa=5000, structural="steel_frame", typology="institutional")  # no steel_kg/rcc_cum
    result = company_history.historical_ranges("acme")
    assert result["n_reference_projects"] == 1
    assert result["structural_system_type_counts"] == {"steel_frame": 1}
    assert result["gfa_sqm_range"]["n"] == 1
    assert result["steel_reinforcement_ratio_kg_per_sqm"] is None
    assert result["concrete_vol_per_sqm"] is None


def test_mt_unit_steel_quantity_converted_to_kg():
    reference_store.upsert_metadata("proj_mt", structural_system_type="rcc_frame", typology="residential", gfa_sqm=1000, company_id="acme")
    boq_cache.save_extraction("proj_mt", {"materials": {
        "reinforcement_steel": {"deterministic": {"quantity": 65.0, "unit": "MT"}},
    }}, company_id="acme")
    result = company_history.historical_ranges("acme")
    ratio = result["steel_reinforcement_ratio_kg_per_sqm"]
    assert ratio["min"] == pytest.approx(65.0)  # 65 MT * 1000 / 1000 sqm


def test_companies_are_isolated():
    _register("a1", gfa=10000, structural="rcc_frame", typology="residential", steel_kg=650000, rcc_cum=4000, company_id="acme")
    _register("b1", gfa=8000, structural="rcc_frame", typology="residential", steel_kg=500000, rcc_cum=3200, company_id="beta")

    acme_history = company_history.historical_ranges("acme")
    beta_history = company_history.historical_ranges("beta")
    assert acme_history["n_reference_projects"] == 1
    assert beta_history["n_reference_projects"] == 1
    assert acme_history["gfa_sqm_range"]["min"] == 10000
    assert beta_history["gfa_sqm_range"]["min"] == 8000