"""GRIHA V6.0 Criterion 21 estimator: "Reduction in Global Warming
Potential through Life Cycle Assessment."

Source: GRIHA Version 6.0 (GRIHA Council, September 2025), Criterion 21,
Table 21.1c -- "Primary materials" column only (this estimator computes
Alternative 1's scope: Frame concrete + steel; real Alternative 1 also
includes Slab, Roof structure, and Roof covering, which this pipeline
doesn't compute separately -- see LIMITATIONS below).

Point thresholds (Table 21.1c, Primary materials column):
  >= 25% GWP reduction from baseline -> 1 point
  >= 30% GWP reduction from baseline -> 3 points
  >= 35% GWP reduction from baseline -> 5 points
  (max 5 points)

Baseline methodology: GRIHA's own text (both V6.0's Methodology section
and V.2019's Criterion 20, Table 20.1c footnote, which states this
explicitly and was used to confirm the approach) says the base case must
be prepared "considering the same size, function, orientation, material
quantities" as the design case -- i.e. same building, same quantities,
different material CHOICE. This estimator follows that principle
directly: it reuses the actual project's own computed concrete volume
and steel mass, substituting in baseline material factors, rather than
inventing a separately-sized reference building.

KNOWN LIMITATIONS -- read before treating this as more than an internal
planning estimate:

1. Baseline material spec: GRIHA's document specifies "M-40" concrete
   and "Fe415" steel for the baseline -- a strength GRADE, not a cement
   TYPE. This pipeline's primary concrete data (IFC) is keyed by cement
   type (OPC/PSC/PPC), not grade. GRIHA's document does not state which
   cement blend the M-40 baseline uses, so OPC (the no-blend, most
   conservative option) is assumed here as OUR OWN interpretive choice,
   not something GRIHA states explicitly. Grade-level (M-40 vs. other
   grades) and steel-yield-strength (Fe415 vs. Fe550 etc.) distinctions
   are NOT reflected numerically -- this pipeline's emission factors
   don't vary by those parameters, which is a real granularity
   limitation of the underlying data, not unique to this estimator.

2. A raw baseline material-factor table DOES appear in GRIHA V6.0's own
   Table 21.3c (a "Frame" row listing a GHG figure of 36.4 kg CO2 per kg
   material) -- but that figure could not be reconciled against any
   physically sensible per-kg GWP value for concrete or steel under any
   interpretation checked (it's 250-350x too high for concrete alone,
   12-20x too high for steel alone, and doesn't match a plausible
   concrete/steel mass-weighted blend either). Rather than guess at what
   it represents, this estimator uses this pipeline's own already-
   verified IFC/CEA-adjusted factors for the baseline instead, following
   the "same quantities, baseline material choice" principle GRIHA's own
   text supports elsewhere. If Table 21.3c's figure is ever resolved
   (e.g. by consulting GRIHA directly or their online panel), this
   module should be revisited.

3. Scope: this pipeline computes Frame (concrete + steel) only.
   Table 21.1c's "Primary materials" scope (Alternative 1) also
   includes Slab, Roof structure, and Roof covering per GRIHA's
   material list -- not computed here. The resulting percentage
   reduction is a PARTIAL estimate of the true Alternative 1 scope,
   not a complete one.

4. This is NOT the official GRIHA-panel computation. Real certification
   requires a third-party LCA calculator, Environmental Product
   Declarations (EPDs), submission through GRIHA's online panel, and
   GRIHA Council's own review -- this estimator is for internal
   planning/target-setting only, and is labeled as such wherever it's
   surfaced.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.project_schema import ProjectSchema
from app.services.calculation_engine import CalculationResult
from app.services.ice_factors import get_concrete_factor_per_m3, get_steel_rebar_factor_per_kg

# Table 21.1c, "Primary materials" column -- GRIHA V6.0, Criterion 21.
# (percentage_reduction_threshold, points)
PRIMARY_MATERIALS_THRESHOLDS = [
    (35.0, 5),
    (30.0, 3),
    (25.0, 1),
]

# Our own interpretive default for the baseline cement blend -- see
# LIMITATIONS #1 above. Not stated explicitly by GRIHA's document.
BASELINE_CEMENT_TYPE = "OPC"


class GrihaCriterion21Estimate(BaseModel):
    project_id: str
    baseline_gwp_kg: float
    design_gwp_kg: float
    pct_reduction: float
    points_estimated: int
    max_points: int = 5
    scope_note: str = (
        "Estimate covers Frame (concrete + steel) only -- a partial subset "
        "of GRIHA's full 'Primary materials' scope (Alternative 1), which "
        "also includes Slab, Roof structure, and Roof covering."
    )
    disclaimer: str = (
        "INTERNAL PLANNING ESTIMATE ONLY -- based on GRIHA Version 6.0 "
        "(Sept 2025), Criterion 21, Table 21.1c point thresholds. Baseline "
        "assumes OPC cement (GRIHA's M-40/Fe415 spec does not state a "
        "cement blend -- OPC is this tool's own conservative default "
        "assumption, not a GRIHA-stated one). This is NOT the official "
        "GRIHA-panel computation, which requires a third-party LCA "
        "calculator, EPDs, and submission through GRIHA's own online panel."
    )


def _find_quantity_by_unit(result: CalculationResult, unit: str) -> float:
    """Pulls a material's quantity from the calculation breakdown by
    unit rather than by list position, so this doesn't silently break if
    calculation_engine.py's breakdown ordering ever changes.
    """
    for item in result.breakdown:
        if item.quantity_unit == unit:
            return item.quantity
    raise ValueError(f"No breakdown item found with unit '{unit}'")


def estimate_criterion_21(project: ProjectSchema, actual_result: CalculationResult) -> GrihaCriterion21Estimate:
    """Estimates points toward GRIHA V6.0 Criterion 21 (Alternative 1 --
    Primary materials scope), using the project's own actual concrete/
    steel quantities against a same-quantity baseline built from
    baseline material assumptions (see module docstring, LIMITATIONS #1).
    """
    concrete_vol_m3 = _find_quantity_by_unit(actual_result, "m3")
    steel_kg = _find_quantity_by_unit(actual_result, "kg")

    baseline_concrete_factor, _ = get_concrete_factor_per_m3(
        cement_type=BASELINE_CEMENT_TYPE, apply_cea=True
    )
    baseline_steel_factor, _ = get_steel_rebar_factor_per_kg(apply_cea=True)

    baseline_gwp_kg = (concrete_vol_m3 * baseline_concrete_factor) + (steel_kg * baseline_steel_factor)
    design_gwp_kg = actual_result.total_carbon_kg

    pct_reduction = ((baseline_gwp_kg - design_gwp_kg) / baseline_gwp_kg * 100) if baseline_gwp_kg else 0.0

    points = 0
    for threshold, pts in PRIMARY_MATERIALS_THRESHOLDS:
        if pct_reduction >= threshold:
            points = pts
            break

    return GrihaCriterion21Estimate(
        project_id=project.project_id,
        baseline_gwp_kg=baseline_gwp_kg,
        design_gwp_kg=design_gwp_kg,
        pct_reduction=round(pct_reduction, 2),
        points_estimated=points,
    )