"""Workstream 06: tests for GFA-closeness ranking in
reference_store.find_candidates() and its use by boq_match.py --
replacing the old "v1: first match wins" behavior.
"""

from __future__ import annotations

import pytest

from app.schemas.project_schema import FieldValue, MandatoryFields, ProjectSchema, StructuralSystemType
from app.services import boq_cache, boq_match, company_store, reference_store


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def _register(slug, gfa, steel_kg, rcc_cum, company_id="acme"):
    reference_store.upsert_metadata(slug, structural_system_type="rcc_frame", typology="residential", gfa_sqm=gfa, company_id=company_id)
    boq_cache.save_extraction(slug, {"materials": {
        "reinforcement_steel": {"deterministic": {"quantity": steel_kg, "unit": "kg"}},
        "rcc": {"deterministic": {"quantity": rcc_cum}},
    }}, company_id=company_id)


def test_find_candidates_ranks_by_gfa_closeness():
    _register("far", gfa=50000, steel_kg=1, rcc_cum=1)
    _register("near", gfa=10500, steel_kg=1, rcc_cum=1)
    _register("mid", gfa=15000, steel_kg=1, rcc_cum=1)

    candidates = reference_store.find_candidates(structural_system_type="rcc_frame", target_gfa_sqm=10000, company_id="acme")
    assert [c["slug"] for c in candidates] == ["near", "mid", "far"]


def test_find_candidates_without_target_gfa_keeps_prior_order_unranked():
    # No target_gfa_sqm given -- ranking is skipped entirely, same as
    # every caller before this workstream (backward compatible).
    _register("b_proj", gfa=50000, steel_kg=1, rcc_cum=1)
    _register("a_proj", gfa=10000, steel_kg=1, rcc_cum=1)
    candidates = reference_store.find_candidates(structural_system_type="rcc_frame", company_id="acme")
    assert {c["slug"] for c in candidates} == {"a_proj", "b_proj"}  # both present, order not asserted


def test_boq_match_derives_ratios_from_nearest_gfa_reference_not_first_in_list():
    # "far" is registered FIRST (would have won under the old first-match
    # behavior) but "near" is the genuinely closer GFA match -- the
    # derived ratio must come from "near".
    _register("far", gfa=50000, steel_kg=2_500_000, rcc_cum=20000, company_id="provident")
    _register("near", gfa=10500, steel_kg=630_000, rcc_cum=4200, company_id="provident")

    project = ProjectSchema(
        project_id="p1",
        company_id="provident",
        mandatory=MandatoryFields(
            gfa_sqm=FieldValue(value=10000.0, source="user-entered", confidence=1.0),
            structural_system_type=FieldValue(value=StructuralSystemType.rcc_frame, source="user-entered", confidence=1.0),
        ),
    )
    result = boq_match.match_boq_defaults(project)

    derived = result.__dict__["_derived"]
    assert derived["matched_reference"] == "near"
    # near: 4200 Cum / 10500 sqm = 0.4 m3/sqm
    assert derived["concrete_vol_per_sqm"] == pytest.approx(0.4)