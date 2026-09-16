"""Workstream 10: Phase 3 -- cumulative bills, running carbon, and the
data a dashboard needs. Builds on this project's roadmap design sketch
("Phase 3 design sketch" section) rather than inventing a new shape:

- Cumulative bill ingestion reuses boq_carbon's existing parser/engine --
  a bill IS shaped like a smaller, periodic BOQ (material, quantity-TO-
  DATE, amount), so calculate_from_boq() is called as-is, unmodified, on
  each uploaded bill file. No new parsing logic exists in this module.

- "Quantity-to-date" is the operative phrase from the roadmap's own
  design sketch: each bill is a CUMULATIVE snapshot (as of that billing
  date, here's everything executed so far), not an incremental delta
  since the last bill. That means the most recent bill period IS
  "billed to date" on its own -- periods are never summed together, only
  compared against each other as points on a time series. Getting this
  wrong (summing cumulative figures across periods) would double- or
  triple-count the same work; this module never does that.

- Running-carbon projection compares billed-to-date value against a
  recorded PROJECT BASELINE's total scope value to derive a percent-
  complete, then extrapolates a projected total -- "against the Phase 2
  benchmark's total scope (or against a stated percent-complete, when
  the bill provides one)", exactly as the roadmap specifies. The
  baseline itself is just a stored BoqCarbonResult/WoCarbonResult from
  the SAME Phase 2 engines every other workstream already uses --
  Phase 2 is normally stateless (see boq_carbon_substitute.py's own
  docstring), so this module is what gives ONE specific project's
  original full-scope calculation a place to live so later bills have
  something to compare against.

- Cost-carbon relationship: every BOQ/bill line item already carries
  both `amount` (Rupees) and `gwp_kg_co2e` (added across Workstream 07's
  coverage work) side by side -- so "cost per kg CO2e" is a division on
  data the engine already computed, never a new model.

- The dashboard's comparison line reuses benchmark.py's own "typical
  building held at typical material choices" concept (not a second
  benchmarking concept) -- see _typical_building_carbon_per_sqm below,
  which calls benchmark.py's own build_baseline_project() +
  calculate_embodied_carbon(), the exact same functions Phase 1's own
  /substitute and /calculate endpoints already use.

Storage layout (Workstream 04 company-scoped convention, extended):
    data/companies/<company_id>/projects/<project_id>/phase3_baseline.json
    data/companies/<company_id>/projects/<project_id>/bills/<period>.json

Workstream 11 additions:
- A third baseline source, "phase1_estimate" (baseline_from_phase1_estimate
  below), for a "running project without a [real] baseline" -- one being
  tracked before any Bill of Quantities exists. Reuses Phase 1's own
  calculate_embodied_carbon()/estimate_cost() functions (the same ones
  app/api/calculate.py already calls) against that project_id's existing
  Phase 1 record, rather than inventing a second estimation path.
  Phase3Baseline.is_estimated=True marks it so, surfaced on the dashboard
  so nothing mistakes an estimate for a priced baseline.
- list_projects() (+ ProjectSummary), answering "show me my projects to
  pick from" -- the union of every project with a Phase 1 record and
  every project with Phase 3 data, since a Phase-1-only project is
  exactly the case a user would want to see in order to start tracking
  it.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.services import company_store, project_store
from app.services.boq_carbon.engine import BoqCarbonResult, FloorAreaBasis
from app.services.coverage import Coverage
from app.services.wo_carbon.wo_carbon_engine import WoCarbonResult

# Workstream 11: "phase1_estimate" is a project that hasn't been billed
# against a real Bill of Quantities/Work Order yet -- a "running project
# without a baseline" in the sense the roadmap always meant it (no real
# BOQ/WO baseline recorded), but still trackable by reusing Phase 1's own
# tiered conceptual estimator for a starting figure. See
# baseline_from_phase1_estimate() below.
BaselineSourceType = Literal["boq", "wo", "phase1_estimate"]


class Phase3Baseline(BaseModel):
    project_id: str
    company_id: str
    source_type: BaselineSourceType
    source_file: str
    recorded_at: str  # ISO datetime this baseline was recorded
    total_gwp_kg_co2e: float
    total_value: float  # the full scope's total priced value (Coverage.total_value -- computed + excluded lines alike)
    floor_area_sqm: Optional[float] = None
    floor_area_basis: Optional[FloorAreaBasis] = None
    structural_system_type: Optional[str] = None
    num_floors: Optional[int] = None
    typology: Optional[str] = None
    coverage: Optional[Coverage] = None
    # Workstream 11: True only for source_type="phase1_estimate" -- an
    # ESTIMATED figure from Phase 1's tiered conceptual estimator, not a
    # real Bill of Quantities/Work Order. Surfaced on the dashboard (see
    # compute_dashboard's notes) so nothing downstream mistakes an
    # estimate for a priced baseline. False (the honest default) for
    # every "boq"/"wo" baseline, which really is a full-scope calculation
    # from an uploaded document.
    is_estimated: bool = False
    note: str = (
        "The original, full-scope Phase 2 calculation for this project -- "
        "every bill recorded against this project is compared against "
        "this baseline's total_value/total_gwp_kg_co2e, never against "
        "another bill."
    )


class BillPeriod(BaseModel):
    project_id: str
    company_id: str
    period: str  # a human label, also the storage filename -- e.g. "2026-Q3"
    billed_date: str  # ISO date -- the actual ordering key for the time series, NOT `period`'s string sort order
    source_file: str
    recorded_at: str
    stated_percent_complete: Optional[float] = None  # 0-100, if the bill itself states progress -- takes priority over a value-derived figure when present
    total_gwp_kg_co2e_to_date: float
    total_value_to_date: float
    cost_per_kg_co2e_to_date: Optional[float] = None  # total_value_to_date / total_gwp_kg_co2e_to_date -- a division on data the engine already computed, not a new model
    coverage: Optional[Coverage] = None
    n_lines_computed: int
    n_lines_total: int


class DashboardPoint(BaseModel):
    """One point on the running-carbon-over-time chart -- one bill period."""

    period: str
    billed_date: str
    total_gwp_kg_co2e_to_date: float
    total_value_to_date: float
    cost_per_kg_co2e_to_date: Optional[float] = None
    stated_percent_complete: Optional[float] = None


class DashboardResult(BaseModel):
    project_id: str
    company_id: str
    baseline: Phase3Baseline
    points: list[DashboardPoint]  # ordered by billed_date, oldest first
    has_bills: bool

    latest_period: Optional[str] = None
    billed_to_date_gwp_kg_co2e: Optional[float] = None
    billed_to_date_value: Optional[float] = None
    cost_per_kg_co2e_to_date: Optional[float] = None

    percent_complete: Optional[float] = None
    percent_complete_source: Optional[str] = None  # "stated_by_latest_bill" | "derived_from_billed_value_vs_baseline_value"

    projected_total_gwp_kg_co2e: Optional[float] = None
    projected_vs_baseline_pct: Optional[float] = None  # positive = tracking to exceed the original full-scope estimate

    benchmark_available: bool = False
    typical_carbon_per_sqm: Optional[float] = None
    projected_carbon_per_sqm: Optional[float] = None
    pct_difference_from_typical: Optional[float] = None
    benchmark_floor_band_used: Optional[str] = None

    notes: list[str] = []


class ProjectSummary(BaseModel):
    """Workstream 11: one row in "show me my projects to pick from" --
    the gap flagged right after WS10 shipped, that a frontend had no way
    to list what projects exist without already knowing their
    project_id. Deliberately the UNION of two sources, not just whichever
    projects already have Phase 3 data: a project that only ever went
    through Phase 1's tiered form (no BOQ/WO/estimate baseline recorded
    yet) still needs to show up here, since that's exactly the case a
    user would pick "track this as a running project" for.
    """

    project_id: str
    company_id: str
    project_name: Optional[str] = None  # from the Phase 1 record at this project_id, if one exists; falls back to project_id itself for display when absent
    has_phase1_record: bool
    has_baseline: bool
    baseline_source_type: Optional[BaselineSourceType] = None
    baseline_is_estimated: bool = False
    n_bills: int
    latest_bill_period: Optional[str] = None
    latest_billed_date: Optional[str] = None


def list_projects(company_id: str) -> list[ProjectSummary]:
    """Every project_id this company has EITHER a Phase 1 record for
    (projects/<id>.json) OR any Phase 3 data for (projects/<id>/ --
    a baseline and/or at least one bill) -- the union, not just one
    source, so a brand-new Phase-1-only project and an established
    Phase-3-tracked one both show up in the same list. See
    company_store.project_dir()'s own docstring for why a file and a
    directory of the same name coexist safely here.
    """
    projects_root = company_store.projects_dir(company_id)
    project_ids: set[str] = set()
    if projects_root.exists():
        for entry in projects_root.iterdir():
            if entry.is_dir():
                project_ids.add(entry.name)  # has Phase 3 data (baseline and/or bills)
            elif entry.suffix == ".json":
                project_ids.add(entry.stem)  # a Phase 1 record only

    summaries = []
    for project_id in sorted(project_ids):
        phase1_project = project_store.load_project(project_id, company_id=company_id)
        baseline = load_baseline(company_id, project_id)
        bills = list_bill_periods(company_id, project_id)
        summaries.append(
            ProjectSummary(
                project_id=project_id,
                company_id=company_id,
                project_name=phase1_project.project_name if phase1_project else None,
                has_phase1_record=phase1_project is not None,
                has_baseline=baseline is not None,
                baseline_source_type=baseline.source_type if baseline else None,
                baseline_is_estimated=baseline.is_estimated if baseline else False,
                n_bills=len(bills),
                latest_bill_period=bills[-1].period if bills else None,
                latest_billed_date=bills[-1].billed_date if bills else None,
            )
        )
    return summaries


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


def save_baseline(baseline: Phase3Baseline) -> None:
    path = company_store.phase3_baseline_path(baseline.company_id, baseline.project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline.model_dump(mode="json"), indent=2))


def load_baseline(company_id: str, project_id: str) -> Optional[Phase3Baseline]:
    path = company_store.phase3_baseline_path(company_id, project_id)
    if not path.exists():
        return None
    return Phase3Baseline.model_validate(json.loads(path.read_text()))


def save_bill_period(bill: BillPeriod, overwrite: bool = False) -> None:
    path = company_store.project_bill_path(bill.company_id, bill.project_id, bill.period)
    if path.exists() and not overwrite:
        raise ValueError(
            f"A bill for period '{bill.period}' already exists for project '{bill.project_id}' -- "
            f"pass overwrite=True to replace it, or use a different period label."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bill.model_dump(mode="json"), indent=2))


def load_bill_period(company_id: str, project_id: str, period: str) -> Optional[BillPeriod]:
    path = company_store.project_bill_path(company_id, project_id, period)
    if not path.exists():
        return None
    return BillPeriod.model_validate(json.loads(path.read_text()))


def list_bill_periods(company_id: str, project_id: str) -> list[BillPeriod]:
    """Every recorded bill for this project, ordered by billed_date
    (oldest first) -- NOT by the `period` label's string sort order,
    since period labels are free-text and not guaranteed to sort
    chronologically."""
    bills_dir = company_store.project_bills_dir(company_id, project_id)
    if not bills_dir.exists():
        return []
    bills = [BillPeriod.model_validate(json.loads(p.read_text())) for p in bills_dir.glob("*.json")]
    return sorted(bills, key=lambda b: b.billed_date)


# --------------------------------------------------------------------------
# Building a Phase3Baseline / BillPeriod from an already-computed engine result
# --------------------------------------------------------------------------


def baseline_from_boq_result(
    result: BoqCarbonResult,
    project_id: str,
    company_id: str,
    structural_system_type: Optional[str] = None,
    num_floors: Optional[int] = None,
    typology: Optional[str] = None,
) -> Phase3Baseline:
    total_value = result.coverage.total_value if result.coverage else result.total_gwp_kg_co2e  # extremely unlikely fallback -- coverage is always set by calculate_from_boq as of Workstream 07
    return Phase3Baseline(
        project_id=project_id,
        company_id=company_id,
        source_type="boq",
        source_file=result.source_file,
        recorded_at=datetime.utcnow().isoformat(),
        total_gwp_kg_co2e=result.total_gwp_kg_co2e,
        total_value=total_value,
        floor_area_sqm=result.floor_area_sqm,
        floor_area_basis=result.floor_area_basis,
        structural_system_type=structural_system_type,
        num_floors=num_floors,
        typology=typology,
        coverage=result.coverage,
    )


def baseline_from_wo_result(
    result: WoCarbonResult,
    project_id: str,
    company_id: str,
    structural_system_type: Optional[str] = None,
    num_floors: Optional[int] = None,
    typology: Optional[str] = None,
) -> Phase3Baseline:
    total_value = result.coverage.total_value if result.coverage else result.total_wo_amount
    return Phase3Baseline(
        project_id=project_id,
        company_id=company_id,
        source_type="wo",
        source_file=result.source_file,
        recorded_at=datetime.utcnow().isoformat(),
        total_gwp_kg_co2e=result.total_gwp_kg_co2e,
        total_value=total_value,
        floor_area_sqm=result.floor_area_sqm,
        floor_area_basis=result.floor_area_basis,
        structural_system_type=structural_system_type,
        num_floors=num_floors,
        typology=typology,
        coverage=result.coverage,
    )


def baseline_from_phase1_estimate(project_id: str, company_id: str) -> Phase3Baseline:
    """Workstream 11: builds a Phase3Baseline from a project's existing
    Phase 1 record instead of an uploaded BOQ/WO -- for a "running
    project without a [real] baseline", i.e. one being tracked before any
    Bill of Quantities exists yet. Deliberately reuses Phase 1's OWN
    calculation functions (calculate_embodied_carbon, estimate_cost) --
    the same ones app/api/calculate.py already calls -- rather than
    inventing a second estimation path; this module's only job is to
    reshape that result into a Phase3Baseline.

    Requires a Phase 1 project to already exist at this exact project_id
    (via POST /form) -- this is intentional: it's what makes a Phase 3
    project's project_id the SAME identifier as its Phase 1 record,
    rather than a second id space the frontend has to keep in sync by
    hand.
    """
    from app.services.calculation_engine import calculate_embodied_carbon
    from app.services.cost_estimation import estimate_cost

    project = project_store.load_project(project_id, company_id=company_id)
    if project is None:
        raise ValueError(
            f"No Phase 1 project record found for '{project_id}' in company '{company_id}' -- "
            f"submit it via POST /form first (Phase 1's tiered estimator), or record a real "
            f"BOQ/WO baseline instead via source_type='boq'/'wo'."
        )
    if project.mandatory.gfa_sqm.value is None:
        raise ValueError(
            f"Project '{project_id}' has no gfa_sqm set yet -- Phase 1's calculation engine needs "
            f"at least a valid GFA before an estimated baseline can be computed."
        )

    carbon_result = calculate_embodied_carbon(project)
    cost_result = estimate_cost(project, carbon_result)

    return Phase3Baseline(
        project_id=project_id,
        company_id=company_id,
        source_type="phase1_estimate",
        source_file=f"phase1-estimate:{project_id}",
        recorded_at=datetime.utcnow().isoformat(),
        total_gwp_kg_co2e=carbon_result.total_carbon_kg,
        total_value=cost_result.total_cost_inr,
        floor_area_sqm=carbon_result.gfa_sqm,
        # Phase 1's GFA isn't classified into Phase 2's net/built-up/
        # carpet taxonomy -- "other" is the honest choice rather than
        # guessing one of the three real bases.
        floor_area_basis="other",
        # .value here is FieldValue's own wrapper attribute; structural_system_type
        # and typology are themselves FieldValue[<Enum>], so a second .value is
        # needed to get the raw string out of the enum member (StructuralSystemType/
        # Typology are both `str, Enum` mixins -- storing the member itself would
        # technically still serialize correctly, but the second .value is explicit
        # and matches every other call site in this module, which always passes
        # a plain str here).
        structural_system_type=(
            project.mandatory.structural_system_type.value.value
            if project.mandatory.structural_system_type.value is not None
            else None
        ),
        num_floors=project.tier2.num_floors.value,
        typology=(
            project.tier2.typology.value.value
            if project.tier2.typology.value is not None
            else None
        ),
        is_estimated=True,
        note=(
            "An ESTIMATED baseline from Phase 1's tiered conceptual estimator "
            f"(scope: {carbon_result.scope_note}) -- not a Bill of Quantities, so this total is "
            "narrower in scope and less precise than a real BOQ/WO baseline. Every bill recorded "
            "against this project is still compared only against this baseline's total_value/"
            "total_gwp_kg_co2e, never against another bill. Replace this with a real baseline "
            "(source_type='boq' or 'wo', overwrite=True) once a Bill of Quantities exists."
        ),
    )


def bill_from_boq_result(
    result: BoqCarbonResult,
    project_id: str,
    company_id: str,
    period: str,
    billed_date: str,
    stated_percent_complete: Optional[float] = None,
) -> BillPeriod:
    total_value = result.coverage.total_value if result.coverage else 0.0
    cost_per_kg = (total_value / result.total_gwp_kg_co2e) if result.total_gwp_kg_co2e else None
    return BillPeriod(
        project_id=project_id,
        company_id=company_id,
        period=period,
        billed_date=billed_date,
        source_file=result.source_file,
        recorded_at=datetime.utcnow().isoformat(),
        stated_percent_complete=stated_percent_complete,
        total_gwp_kg_co2e_to_date=result.total_gwp_kg_co2e,
        total_value_to_date=total_value,
        cost_per_kg_co2e_to_date=cost_per_kg,
        coverage=result.coverage,
        n_lines_computed=result.n_lines_computed,
        n_lines_total=result.n_lines_total,
    )


# --------------------------------------------------------------------------
# The dashboard's "typical building" comparison line -- reuses benchmark.py
# --------------------------------------------------------------------------


def _typical_building_carbon_per_sqm(
    floor_area_sqm: float,
    structural_system_type: Optional[str],
    num_floors: Optional[int],
    typology: Optional[str],
) -> tuple[float, str]:
    """Returns (typical_carbon_per_sqm, floor_band_used) by reusing
    benchmark.py's own synthetic "typical building" construction --
    build_baseline_project() + calculate_embodied_carbon() -- the exact
    same functions Phase 1's /substitute and /calculate endpoints already
    run. Not a second benchmarking concept: a genuinely minimal
    ProjectSchema is built here purely as the INPUT geometry
    build_baseline_project() needs (it forces its own typical material
    choices regardless of what this input project's tier3 fields say, so
    those are never set).
    """
    from app.schemas.project_schema import FieldValue, ProjectSchema
    from app.services.benchmark import _get_floor_band, build_baseline_project
    from app.services.calculation_engine import calculate_embodied_carbon

    geometry = ProjectSchema(project_id="phase3-benchmark-geometry")
    geometry.mandatory.gfa_sqm = FieldValue(value=floor_area_sqm, source="user-entered", confidence=1.0)
    if structural_system_type:
        geometry.mandatory.structural_system_type = FieldValue(
            value=structural_system_type, source="user-entered", confidence=1.0
        )
    if num_floors is not None:
        geometry.tier2.num_floors = FieldValue(value=num_floors, source="user-entered", confidence=1.0)
    if typology:
        geometry.tier2.typology = FieldValue(value=typology, source="user-entered", confidence=1.0)

    baseline_project = build_baseline_project(geometry)
    baseline_result = calculate_embodied_carbon(baseline_project)
    floor_band = _get_floor_band(num_floors)
    return baseline_result.carbon_per_sqm, floor_band


# --------------------------------------------------------------------------
# The dashboard itself
# --------------------------------------------------------------------------


def compute_dashboard(company_id: str, project_id: str) -> DashboardResult:
    baseline = load_baseline(company_id, project_id)
    if baseline is None:
        raise ValueError(
            f"No Phase 3 baseline recorded for project '{project_id}' (company '{company_id}') -- "
            f"record one first via POST /phase3/projects/{{project_id}}/baseline before uploading bills "
            f"or requesting a dashboard."
        )

    bills = list_bill_periods(company_id, project_id)
    notes: list[str] = []

    if baseline.is_estimated:
        notes.append(
            "This project's baseline is an ESTIMATED figure from Phase 1's conceptual estimator, "
            "not a real Bill of Quantities -- treat percent-complete, the projected total, and the "
            "benchmark comparison below as correspondingly rougher until a real BOQ/WO baseline "
            "replaces it (POST the baseline again with source_type='boq' or 'wo' and overwrite=True)."
        )

    points = [
        DashboardPoint(
            period=b.period,
            billed_date=b.billed_date,
            total_gwp_kg_co2e_to_date=b.total_gwp_kg_co2e_to_date,
            total_value_to_date=b.total_value_to_date,
            cost_per_kg_co2e_to_date=b.cost_per_kg_co2e_to_date,
            stated_percent_complete=b.stated_percent_complete,
        )
        for b in bills
    ]

    result = DashboardResult(
        project_id=project_id,
        company_id=company_id,
        baseline=baseline,
        points=points,
        has_bills=bool(bills),
    )

    if not bills:
        notes.append("No bills recorded yet -- upload at least one via POST /phase3/projects/{project_id}/bills to see running carbon.")
        result.notes = notes
        return result

    latest = bills[-1]  # cumulative-to-date semantics -- the most recent bill IS the current state, never summed with earlier ones
    result.latest_period = latest.period
    result.billed_to_date_gwp_kg_co2e = latest.total_gwp_kg_co2e_to_date
    result.billed_to_date_value = latest.total_value_to_date
    result.cost_per_kg_co2e_to_date = latest.cost_per_kg_co2e_to_date

    if latest.stated_percent_complete is not None:
        percent_complete = latest.stated_percent_complete
        percent_source = "stated_by_latest_bill"
    elif baseline.total_value:
        percent_complete = min(latest.total_value_to_date / baseline.total_value * 100, 999.0)  # capped display-wise, not silently clamped to 100 -- billing ahead of the original scope estimate is real, useful information
        percent_source = "derived_from_billed_value_vs_baseline_value"
    else:
        percent_complete = None
        percent_source = None
        notes.append("Baseline has no total_value to derive percent-complete from, and no bill has stated one -- projection cannot be computed.")

    result.percent_complete = percent_complete
    result.percent_complete_source = percent_source

    if percent_complete and percent_complete > 0:
        projected_total = latest.total_gwp_kg_co2e_to_date / (percent_complete / 100)
        result.projected_total_gwp_kg_co2e = projected_total
        if baseline.total_gwp_kg_co2e:
            result.projected_vs_baseline_pct = round(
                (projected_total - baseline.total_gwp_kg_co2e) / baseline.total_gwp_kg_co2e * 100, 2
            )
    else:
        notes.append("percent_complete is zero or unavailable -- cannot extrapolate a projected total yet.")

    if baseline.floor_area_sqm and result.projected_total_gwp_kg_co2e:
        try:
            typical_per_sqm, floor_band = _typical_building_carbon_per_sqm(
                baseline.floor_area_sqm,
                baseline.structural_system_type,
                baseline.num_floors,
                baseline.typology,
            )
            projected_per_sqm = result.projected_total_gwp_kg_co2e / baseline.floor_area_sqm
            result.benchmark_available = True
            result.typical_carbon_per_sqm = typical_per_sqm
            result.projected_carbon_per_sqm = projected_per_sqm
            result.pct_difference_from_typical = (
                round((projected_per_sqm - typical_per_sqm) / typical_per_sqm * 100, 2) if typical_per_sqm else None
            )
            result.benchmark_floor_band_used = floor_band
        except ValueError as e:
            notes.append(f"Benchmark comparison unavailable: {e}")
    elif not baseline.floor_area_sqm:
        notes.append("Baseline has no floor_area_sqm recorded -- the typical-building benchmark comparison isn't available for this project.")

    result.notes = notes
    return result