"""Workstream 10: tests for Phase 3 (project baseline, periodic bills,
running-carbon dashboard) -- app/services/phase3.py and app/api/phase3.py.

Isolated the same way tests/test_company_storage.py already established:
every test redirects company_store.COMPANIES_DIR to a pytest tmp_path,
so nothing here touches the real app/data/companies/provident/ tree.

Uses the real Ecopolitan BOQ (same reference document every other
workstream's tests already use) as both the baseline upload and a stand-
in "bill" upload -- skipped, not failed, if that file isn't present in
this environment, matching tests/test_engine_coverage.py's own pattern.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.schemas.project_schema import (
    FieldValue,
    MandatoryFields,
    ProjectSchema,
    StructuralSystemType,
    Tier2Fields,
    Typology,
)
from app.services import company_store, phase3, project_store
from tests.golden_utils import load_golden, source_file_exists

client = TestClient(__import__("app.main", fromlist=["app"]).app)

COMPANY = "provident"


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


@pytest.fixture()
def ecopolitan_boq_path() -> str:
    golden = load_golden("ecopolitan_boq")
    skip_reason = source_file_exists(golden)
    if skip_reason:
        pytest.skip(skip_reason)
    return golden["_meta"]["source_path"]


# --------------------------------------------------------------------------
# app/services/phase3.py -- unit tests against small, hand-built models
# (no BOQ parsing involved, so these run instantly and don't depend on
# the reference file being present)
# --------------------------------------------------------------------------


def _baseline(project_id="proj-1", company_id=COMPANY, total_value=1_000_000.0, total_gwp=100_000.0, floor_area=None, **kw):
    return phase3.Phase3Baseline(
        project_id=project_id,
        company_id=company_id,
        source_type="boq",
        source_file="test.xlsx",
        recorded_at="2026-01-01T00:00:00",
        total_gwp_kg_co2e=total_gwp,
        total_value=total_value,
        floor_area_sqm=floor_area,
        **kw,
    )


def _bill(project_id="proj-1", company_id=COMPANY, period="2026-Q1", billed_date="2026-03-31", value=500_000.0, gwp=50_000.0, stated_pct=None):
    return phase3.BillPeriod(
        project_id=project_id,
        company_id=company_id,
        period=period,
        billed_date=billed_date,
        source_file="bill.xlsx",
        recorded_at="2026-04-01T00:00:00",
        stated_percent_complete=stated_pct,
        total_gwp_kg_co2e_to_date=gwp,
        total_value_to_date=value,
        cost_per_kg_co2e_to_date=(value / gwp) if gwp else None,
        n_lines_computed=10,
        n_lines_total=10,
    )


def test_baseline_round_trip():
    b = _baseline()
    phase3.save_baseline(b)
    loaded = phase3.load_baseline(COMPANY, "proj-1")
    assert loaded == b


def test_load_baseline_missing_returns_none():
    assert phase3.load_baseline(COMPANY, "no-such-project") is None


def test_bill_round_trip_and_duplicate_rejected_without_overwrite():
    bill = _bill()
    phase3.save_bill_period(bill)
    loaded = phase3.load_bill_period(COMPANY, "proj-1", "2026-Q1")
    assert loaded == bill

    with pytest.raises(ValueError, match="already exists"):
        phase3.save_bill_period(bill)

    # overwrite=True succeeds
    bill2 = _bill(value=600_000.0, gwp=60_000.0)
    phase3.save_bill_period(bill2, overwrite=True)
    assert phase3.load_bill_period(COMPANY, "proj-1", "2026-Q1").total_value_to_date == 600_000.0


def test_list_bill_periods_sorts_by_billed_date_not_period_label():
    # Period labels deliberately out of chronological order relative to
    # their billed_date, to prove the sort key is billed_date.
    phase3.save_bill_period(_bill(period="B-second", billed_date="2026-06-30"))
    phase3.save_bill_period(_bill(period="A-first", billed_date="2026-03-31"))
    bills = phase3.list_bill_periods(COMPANY, "proj-1")
    assert [b.period for b in bills] == ["A-first", "B-second"]


def test_list_bill_periods_empty_for_unknown_project():
    assert phase3.list_bill_periods(COMPANY, "no-such-project") == []


def test_compute_dashboard_raises_without_a_baseline():
    with pytest.raises(ValueError, match="No Phase 3 baseline"):
        phase3.compute_dashboard(COMPANY, "no-such-project")


def test_compute_dashboard_no_bills_yet():
    phase3.save_baseline(_baseline())
    d = phase3.compute_dashboard(COMPANY, "proj-1")
    assert d.has_bills is False
    assert d.points == []
    assert d.latest_period is None
    assert any("No bills recorded" in n for n in d.notes)


def test_compute_dashboard_uses_stated_percent_complete_when_given():
    phase3.save_baseline(_baseline(total_value=1_000_000.0, total_gwp=100_000.0))
    phase3.save_bill_period(_bill(value=500_000.0, gwp=40_000.0, stated_pct=40.0))

    d = phase3.compute_dashboard(COMPANY, "proj-1")
    assert d.percent_complete == 40.0
    assert d.percent_complete_source == "stated_by_latest_bill"
    # projected = billed_gwp / (pct/100) = 40000 / 0.4 = 100000
    assert d.projected_total_gwp_kg_co2e == pytest.approx(100_000.0)
    assert d.projected_vs_baseline_pct == pytest.approx(0.0)


def test_compute_dashboard_derives_percent_complete_from_value_when_not_stated():
    phase3.save_baseline(_baseline(total_value=1_000_000.0, total_gwp=200_000.0))
    phase3.save_bill_period(_bill(value=250_000.0, gwp=40_000.0, stated_pct=None))

    d = phase3.compute_dashboard(COMPANY, "proj-1")
    assert d.percent_complete_source == "derived_from_billed_value_vs_baseline_value"
    assert d.percent_complete == pytest.approx(25.0)  # 250k / 1M
    assert d.projected_total_gwp_kg_co2e == pytest.approx(160_000.0)  # 40000 / 0.25
    # baseline is 200000, projected is 160000 -- tracking UNDER the baseline estimate
    assert d.projected_vs_baseline_pct == pytest.approx(-20.0)


def test_compute_dashboard_only_uses_latest_period_not_a_sum_of_periods():
    """Cumulative-to-date semantics: the most recent bill IS the current
    state. Summing an earlier period's total on top would double-count
    the same work -- this is the single most important correctness
    property of this workstream."""
    phase3.save_baseline(_baseline(total_value=1_000_000.0, total_gwp=200_000.0))
    phase3.save_bill_period(_bill(period="2026-Q1", billed_date="2026-03-31", value=250_000.0, gwp=40_000.0))
    phase3.save_bill_period(_bill(period="2026-Q2", billed_date="2026-06-30", value=500_000.0, gwp=90_000.0))

    d = phase3.compute_dashboard(COMPANY, "proj-1")
    assert d.latest_period == "2026-Q2"
    assert d.billed_to_date_value == pytest.approx(500_000.0)  # NOT 750,000
    assert d.billed_to_date_gwp_kg_co2e == pytest.approx(90_000.0)  # NOT 130,000
    assert len(d.points) == 2  # but both periods still show up as separate chart points


def test_compute_dashboard_benchmark_requires_floor_area():
    phase3.save_baseline(_baseline(total_value=1_000_000.0, total_gwp=200_000.0, floor_area=None))
    phase3.save_bill_period(_bill(value=1_000_000.0, gwp=200_000.0, stated_pct=100.0))
    d = phase3.compute_dashboard(COMPANY, "proj-1")
    assert d.benchmark_available is False
    assert any("floor_area_sqm" in n for n in d.notes)


def test_compute_dashboard_benchmark_available_with_floor_area():
    phase3.save_baseline(_baseline(total_value=1_000_000.0, total_gwp=200_000.0, floor_area=50_000.0))
    phase3.save_bill_period(_bill(value=1_000_000.0, gwp=200_000.0, stated_pct=100.0))
    d = phase3.compute_dashboard(COMPANY, "proj-1")
    assert d.benchmark_available is True
    assert d.typical_carbon_per_sqm is not None
    assert d.projected_carbon_per_sqm == pytest.approx(200_000.0 / 50_000.0)
    assert d.benchmark_floor_band_used == "mid_rise"  # no num_floors given -- benchmark.py's own documented default


def test_zero_baseline_total_value_gives_no_percent_complete():
    phase3.save_baseline(_baseline(total_value=0.0, total_gwp=200_000.0))
    phase3.save_bill_period(_bill(value=100.0, gwp=10.0, stated_pct=None))
    d = phase3.compute_dashboard(COMPANY, "proj-1")
    assert d.percent_complete is None
    assert d.projected_total_gwp_kg_co2e is None
    assert any("cannot be computed" in n for n in d.notes)


# --------------------------------------------------------------------------
# app/api/phase3.py -- endpoint tests against the real Ecopolitan BOQ
# --------------------------------------------------------------------------


def test_baseline_endpoint_records_a_real_boq(ecopolitan_boq_path):
    with open(ecopolitan_boq_path, "rb") as f:
        r = client.post(
            "/phase3/projects/proj-api/baseline",
            data={
                "source_type": "boq",
                "floor_area_sqm": "205981.65",
                "floor_area_basis": "built_up_total",
                "company_id": COMPANY,
                "structural_system_type": "rcc_frame",
                "num_floors": "20",
            },
            files={"file": ("Ecopolitan_BOQ.xlsx", f.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_gwp_kg_co2e"] > 0
    assert body["total_value"] > 0
    assert body["floor_area_sqm"] == 205981.65


def test_baseline_endpoint_rejects_duplicate_without_overwrite(ecopolitan_boq_path):
    with open(ecopolitan_boq_path, "rb") as f:
        data = f.read()
    files = {"file": ("Ecopolitan_BOQ.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r1 = client.post("/phase3/projects/proj-dup/baseline", data={"source_type": "boq", "company_id": COMPANY}, files=files)
    assert r1.status_code == 200

    files2 = {"file": ("Ecopolitan_BOQ.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r2 = client.post("/phase3/projects/proj-dup/baseline", data={"source_type": "boq", "company_id": COMPANY}, files=files2)
    assert r2.status_code == 400
    assert "already has a Phase 3 baseline" in r2.json()["detail"]

    files3 = {"file": ("Ecopolitan_BOQ.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r3 = client.post(
        "/phase3/projects/proj-dup/baseline",
        data={"source_type": "boq", "company_id": COMPANY, "overwrite": "true"},
        files=files3,
    )
    assert r3.status_code == 200


def test_baseline_endpoint_validates_floor_area_pairing(ecopolitan_boq_path):
    with open(ecopolitan_boq_path, "rb") as f:
        r = client.post(
            "/phase3/projects/proj-pairing/baseline",
            data={"source_type": "boq", "company_id": COMPANY, "floor_area_sqm": "1000"},  # basis omitted
            files={"file": ("Ecopolitan_BOQ.xlsx", f.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert r.status_code == 400


def test_bills_endpoint_requires_a_baseline_first(ecopolitan_boq_path):
    with open(ecopolitan_boq_path, "rb") as f:
        r = client.post(
            "/phase3/projects/proj-no-baseline/bills",
            data={"period": "2026-Q1", "billed_date": "2026-03-31", "company_id": COMPANY},
            files={"bill_file": ("bill.xlsx", f.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert r.status_code == 400
    assert "no Phase 3 baseline" in r.json()["detail"]


def test_bills_endpoint_full_flow_and_dashboard(ecopolitan_boq_path):
    with open(ecopolitan_boq_path, "rb") as f:
        boq_bytes = f.read()

    r_baseline = client.post(
        "/phase3/projects/proj-flow/baseline",
        data={
            "source_type": "boq", "company_id": COMPANY,
            "floor_area_sqm": "205981.65", "floor_area_basis": "built_up_total",
        },
        files={"file": ("Ecopolitan_BOQ.xlsx", boq_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r_baseline.status_code == 200

    r_bill = client.post(
        "/phase3/projects/proj-flow/bills",
        data={"period": "2026-Q1", "billed_date": "2026-03-31", "stated_percent_complete": "50", "company_id": COMPANY},
        files={"bill_file": ("bill_q1.xlsx", boq_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r_bill.status_code == 200
    assert r_bill.json()["cost_per_kg_co2e_to_date"] > 0

    # Duplicate period rejected, then accepted with overwrite.
    r_dup = client.post(
        "/phase3/projects/proj-flow/bills",
        data={"period": "2026-Q1", "billed_date": "2026-03-31", "company_id": COMPANY},
        files={"bill_file": ("bill_q1_again.xlsx", boq_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r_dup.status_code == 400

    r_list = client.get("/phase3/projects/proj-flow/bills", params={"company_id": COMPANY})
    assert r_list.status_code == 200
    assert len(r_list.json()) == 1

    r_dash = client.get("/phase3/projects/proj-flow/dashboard", params={"company_id": COMPANY})
    assert r_dash.status_code == 200
    dash = r_dash.json()
    assert dash["has_bills"] is True
    assert dash["percent_complete"] == 50.0
    assert dash["benchmark_available"] is True


def test_dashboard_endpoint_404_for_missing_baseline():
    r = client.get("/phase3/projects/no-such-project/dashboard", params={"company_id": COMPANY})
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Workstream 11 -- "running project without a [real] baseline": a Phase 3
# baseline built from Phase 1's own conceptual estimator instead of an
# uploaded BOQ/WO, plus the project registry (list_projects/ProjectSummary)
# that lets a frontend show a picklist instead of requiring an already-known
# project_id.
# --------------------------------------------------------------------------


def _save_phase1_project(project_id="p1-proj", company_id=COMPANY, name="Test Tower", gfa=50_000.0):
    project = ProjectSchema(
        project_id=project_id,
        company_id=company_id,
        project_name=name,
        mandatory=MandatoryFields(
            gfa_sqm=FieldValue(value=gfa, source="user-entered", confidence=1.0),
            location=FieldValue(value="Chennai", source="user-entered", confidence=1.0),
            structural_system_type=FieldValue(
                value=StructuralSystemType.rcc_frame, source="user-entered", confidence=1.0
            ),
        ),
        tier2=Tier2Fields(
            typology=FieldValue(value=Typology.residential, source="user-entered", confidence=1.0),
            num_floors=FieldValue(value=20, source="user-entered", confidence=1.0),
        ),
    )
    project_store.save_project(project)
    return project


def test_baseline_from_phase1_estimate_builds_correct_baseline():
    _save_phase1_project()
    baseline = phase3.baseline_from_phase1_estimate("p1-proj", COMPANY)

    assert baseline.source_type == "phase1_estimate"
    assert baseline.is_estimated is True
    assert baseline.total_gwp_kg_co2e > 0
    assert baseline.total_value > 0
    assert baseline.floor_area_sqm == 50_000.0
    assert baseline.structural_system_type == "rcc_frame"  # plain str, not the enum member -- see the builder's own comment
    assert baseline.typology == "residential"
    assert baseline.num_floors == 20
    assert "ESTIMATED" in baseline.note


def test_baseline_from_phase1_estimate_raises_without_phase1_record():
    with pytest.raises(ValueError, match="No Phase 1 project record"):
        phase3.baseline_from_phase1_estimate("no-such-project", COMPANY)


def test_baseline_from_phase1_estimate_raises_without_gfa():
    project = ProjectSchema(project_id="no-gfa-proj", company_id=COMPANY)  # every field left unset
    project_store.save_project(project)
    with pytest.raises(ValueError, match="no gfa_sqm set"):
        phase3.baseline_from_phase1_estimate("no-gfa-proj", COMPANY)


def test_boq_and_wo_baselines_default_is_estimated_false():
    # Regression guard: a real BOQ/WO baseline (built via the existing
    # WS10 builders, exercised elsewhere in this file through _baseline())
    # must never come back flagged as an estimate.
    b = _baseline()
    assert b.source_type == "boq"
    assert b.is_estimated is False


def test_compute_dashboard_adds_estimated_baseline_note():
    _save_phase1_project()
    baseline = phase3.baseline_from_phase1_estimate("p1-proj", COMPANY)
    phase3.save_baseline(baseline)

    d = phase3.compute_dashboard(COMPANY, "p1-proj")
    assert any("ESTIMATED figure from Phase 1" in n for n in d.notes)


def test_compute_dashboard_no_estimated_note_for_a_real_baseline():
    phase3.save_baseline(_baseline())
    d = phase3.compute_dashboard(COMPANY, "proj-1")
    assert not any("ESTIMATED figure from Phase 1" in n for n in d.notes)


def test_list_projects_empty_for_new_company():
    assert phase3.list_projects(COMPANY) == []


def test_list_projects_includes_phase1_only_project_with_no_baseline():
    _save_phase1_project(project_id="phase1-only", name="Phase 1 Only Tower")
    summaries = phase3.list_projects(COMPANY)
    assert len(summaries) == 1
    s = summaries[0]
    assert s.project_id == "phase1-only"
    assert s.project_name == "Phase 1 Only Tower"
    assert s.has_phase1_record is True
    assert s.has_baseline is False
    assert s.baseline_source_type is None
    assert s.n_bills == 0


def test_list_projects_includes_boq_only_project_with_no_phase1_record():
    # A project that went straight to a Phase 2 BOQ baseline, never
    # through Phase 1's tiered form at all -- must still show up, just
    # with has_phase1_record=False and no name.
    phase3.save_baseline(_baseline(project_id="boq-only"))
    summaries = phase3.list_projects(COMPANY)
    assert len(summaries) == 1
    s = summaries[0]
    assert s.project_id == "boq-only"
    assert s.project_name is None
    assert s.has_phase1_record is False
    assert s.has_baseline is True
    assert s.baseline_source_type == "boq"


def test_list_projects_reflects_baseline_and_bills_and_is_a_union():
    _save_phase1_project(project_id="proj-a", name="Project A")  # Phase 1 only
    _save_phase1_project(project_id="proj-b", name="Project B")
    baseline_b = phase3.baseline_from_phase1_estimate("proj-b", COMPANY)
    phase3.save_baseline(baseline_b)
    phase3.save_bill_period(_bill(project_id="proj-b", period="2026-Q1", billed_date="2026-03-31"))

    summaries = {s.project_id: s for s in phase3.list_projects(COMPANY)}
    assert set(summaries) == {"proj-a", "proj-b"}

    assert summaries["proj-a"].has_baseline is False
    assert summaries["proj-a"].n_bills == 0

    assert summaries["proj-b"].has_baseline is True
    assert summaries["proj-b"].baseline_is_estimated is True
    assert summaries["proj-b"].n_bills == 1
    assert summaries["proj-b"].latest_bill_period == "2026-Q1"


def test_baseline_endpoint_phase1_estimate_source_no_file_needed():
    r_form = client.post(
        "/form",
        json={
            "project_name": "API Estimate Tower",
            "gfa_sqm": 40000,
            "location": "Chennai",
            "structural_system_type": "rcc_frame",
            "typology": "residential",
            "num_floors": 15,
            "company_id": COMPANY,
        },
    )
    assert r_form.status_code == 200
    project_id = r_form.json()["project_id"]

    r_baseline = client.post(
        f"/phase3/projects/{project_id}/baseline",
        data={"source_type": "phase1_estimate", "company_id": COMPANY},
    )
    assert r_baseline.status_code == 200, r_baseline.text
    body = r_baseline.json()
    assert body["source_type"] == "phase1_estimate"
    assert body["is_estimated"] is True
    assert body["total_gwp_kg_co2e"] > 0

    r_list = client.get("/phase3/projects", params={"company_id": COMPANY})
    assert r_list.status_code == 200
    matches = [p for p in r_list.json() if p["project_id"] == project_id]
    assert len(matches) == 1
    assert matches[0]["project_name"] == "API Estimate Tower"
    assert matches[0]["has_baseline"] is True
    assert matches[0]["baseline_is_estimated"] is True


def test_baseline_endpoint_phase1_estimate_requires_an_existing_phase1_project():
    r = client.post(
        "/phase3/projects/no-such-phase1-project/baseline",
        data={"source_type": "phase1_estimate", "company_id": COMPANY},
    )
    assert r.status_code == 400
    assert "No Phase 1 project record" in r.json()["detail"]


def test_projects_list_endpoint_empty_for_new_company():
    r = client.get("/phase3/projects", params={"company_id": COMPANY})
    assert r.status_code == 200
    assert r.json() == []