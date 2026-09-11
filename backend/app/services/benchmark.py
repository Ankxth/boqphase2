"""GRIHA-style baseline benchmark.

GRIHA doesn't publish a ready-made "kgCO2/sqm for a building of size X"
table -- so instead of hunting for a number that doesn't exist, this
builds a "typical" reference building matching the real project's
GEOMETRY (GFA, structural system, typology, floor count) but with
material CHOICES forced to typical/default values (cement type, steel
ratio, concrete grade), then runs it through the exact same calculation
engine used for the real project. The comparison this produces isolates
"did this project choose typical or better-than-typical materials," not
"is this project a different size" -- geometry is held constant on
purpose, only material choice varies between the real project and the
baseline.

This is explicitly NOT an official GRIHA-published benchmark, and is
labeled as such everywhere it's surfaced -- it's a self-computed typical-
building comparison, built the same way GRIHA/ECBC's own methodology
works (compare against a computed reference building), but using this
project's own typical-value assumptions, not GRIHA's own (which aren't
published in this form).

"Typical" material values are the same floor-count-band midpoints used
as prompt guidance in llm_fallback.py (50-70/70-100/100-130 kg/sqm steel
by low/mid/high-rise) -- using the midpoint of each band rather than the
full range, since a single representative baseline number is needed, not
a range.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.project_schema import (
    CementType,
    FieldValue,
    ProjectSchema,
)
from app.services.calculation_engine import CalculationResult, calculate_embodied_carbon

# Floor-count bands and their typical (midpoint) material assumptions.
# Same bands as llm_fallback.py's prompt guidance -- kept consistent
# rather than inventing a second set of numbers.
FLOOR_BANDS = {
    "low_rise": {"max_floors": 4, "steel_kg_per_sqm": 60.0, "concrete_grade": "M25"},
    "mid_rise": {"max_floors": 15, "steel_kg_per_sqm": 85.0, "concrete_grade": "M30"},
    "high_rise": {"max_floors": None, "steel_kg_per_sqm": 115.0, "concrete_grade": "M40"},
}

# Same cement type used as the LLM fallback's placeholder default --
# PPC (fly-ash blend) is the most common choice in current Indian
# construction, per the same reasoning documented in llm_fallback.py.
TYPICAL_CEMENT_TYPE = CementType.ppc

# Same generic concrete-volume-per-sqm assumption calculation_engine.py
# falls back to -- used consistently here so the baseline's concrete
# volume isn't drawn from a different assumption than what the real
# project falls back to when it lacks BOQ data of its own.
TYPICAL_CONCRETE_VOL_PER_SQM = 0.45

# Tag used for every synthetic field on the baseline project. None of
# the existing FieldSource values ("user-entered", "boq-matched",
# "own-boq-extracted", "llm-estimated") precisely describe "a defined
# typical-value assumption, not a guess and not real data" -- but adding
# a new FieldSource just for this would ripple through every place that
# branches on source, so "llm-estimated" is reused here as the closest
# existing category, confidence deliberately set lower (0.3) than a real
# LLM estimate (0.4) to signal it's a fixed assumption, not even a guess.
BASELINE_CONFIDENCE = 0.3


class BenchmarkResult(BaseModel):
    project_id: str
    actual_carbon_per_sqm: float
    baseline_carbon_per_sqm: float
    pct_difference_from_baseline: float  # positive = worse than typical, negative = better
    comparison_label: str  # "above typical" | "at typical" | "below typical"
    floor_band_used: str
    baseline_result: CalculationResult
    disclaimer: str = (
        "This is a self-computed comparison against a typical building of "
        "the same size, structural system, and floor count -- NOT an "
        "official GRIHA-published benchmark. GRIHA does not publish a "
        "ready-made embodied-carbon-per-sqm table; this baseline is built "
        "using this project's own typical-value assumptions and the same "
        "calculation engine used for the real project."
    )


def _get_floor_band(num_floors: int | None) -> str:
    """Defaults to mid_rise when floor count is unknown -- a neutral
    middle assumption rather than guessing high or low.
    """
    if num_floors is None:
        return "mid_rise"
    if num_floors <= FLOOR_BANDS["low_rise"]["max_floors"]:
        return "low_rise"
    if num_floors <= FLOOR_BANDS["mid_rise"]["max_floors"]:
        return "mid_rise"
    return "high_rise"


def build_baseline_project(project: ProjectSchema) -> ProjectSchema:
    """Constructs a synthetic 'typical building' project: same geometry
    as the real project (GFA, structural system, typology, floor count),
    but material choices forced to typical/default values regardless of
    what the real project's own tier3 fields say.
    """
    gfa = project.mandatory.gfa_sqm.value
    if gfa is None or gfa <= 0:
        raise ValueError("Cannot build a baseline without a valid project GFA")

    floor_band = _get_floor_band(project.tier2.num_floors.value)
    band_config = FLOOR_BANDS[floor_band]

    baseline = ProjectSchema(project_id=f"{project.project_id}-baseline")

    # Geometry: copy from the real project so the comparison is fair --
    # same size and structural system, only material choice differs.
    baseline.mandatory.gfa_sqm = project.mandatory.gfa_sqm
    baseline.mandatory.structural_system_type = project.mandatory.structural_system_type
    baseline.mandatory.location = project.mandatory.location
    baseline.tier2.num_floors = project.tier2.num_floors
    baseline.tier2.typology = project.tier2.typology

    # Material choices: forced to typical band values, not copied from
    # the real project.
    baseline.tier3.cement_type = FieldValue(
        value=TYPICAL_CEMENT_TYPE, source="llm-estimated", confidence=BASELINE_CONFIDENCE
    )
    baseline.tier3.concrete_grade_mix = FieldValue(
        value=band_config["concrete_grade"], source="llm-estimated", confidence=BASELINE_CONFIDENCE
    )
    baseline.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(
        value=band_config["steel_kg_per_sqm"], source="llm-estimated", confidence=BASELINE_CONFIDENCE
    )

    # Concrete volume ratio isn't a Tier3Fields field -- calculation_engine.py
    # reads it from _derived, same mechanism boq_match.py and
    # project_boq_refinement.py use.
    baseline.__dict__.setdefault("_derived", {})["concrete_vol_per_sqm"] = TYPICAL_CONCRETE_VOL_PER_SQM

    return baseline


def compute_benchmark(project: ProjectSchema, actual_result: CalculationResult) -> BenchmarkResult:
    """Computes the baseline and compares it against an already-computed
    actual result (pass in the output of calculate_embodied_carbon(project)
    -- this function doesn't recompute the actual project's own result,
    since the caller already has it and recomputing would be wasteful).
    """
    floor_band = _get_floor_band(project.tier2.num_floors.value)
    baseline_project = build_baseline_project(project)
    baseline_result = calculate_embodied_carbon(baseline_project)

    actual_per_sqm = actual_result.carbon_per_sqm
    baseline_per_sqm = baseline_result.carbon_per_sqm

    pct_diff = ((actual_per_sqm - baseline_per_sqm) / baseline_per_sqm) * 100 if baseline_per_sqm else 0.0

    if pct_diff > 5:
        label = "above typical"
    elif pct_diff < -5:
        label = "below typical"
    else:
        label = "at typical"

    return BenchmarkResult(
        project_id=project.project_id,
        actual_carbon_per_sqm=actual_per_sqm,
        baseline_carbon_per_sqm=baseline_per_sqm,
        pct_difference_from_baseline=round(pct_diff, 2),
        comparison_label=label,
        floor_band_used=floor_band,
        baseline_result=baseline_result,
    )