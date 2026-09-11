"""Material emission factor lookup -- IFC India data as PRIMARY source,
ICE v4.1 as FALLBACK.

Why the switch: IFC's figures are built from real Indian production data
(Sphera/GaBi modeling of Indian cement, concrete, and steel production),
whereas ICE's tables are UK/EU-basis figures. Real India-specific data
outranks an adjusted-from-elsewhere figure, even where it gives a higher
(less flattering) number -- confirmed true for both materials switched
here: IFC's steel rebar (2.6 kgCO2e/kg) is 51% higher than ICE's world
average (1.72), and this is used as the new default anyway, on the same
principle.

Real tradeoff, stated plainly: IFC gives concrete GWP by CEMENT TYPE
(OPC/PSC/PPC), not by M-GRADE the way ICE does. Switching to IFC as
primary means trading grade-level precision for cement-type-based real
data. The ICE M-grade table remains available as a fallback for when
cement type is unknown but grade is known.

--- Grade scaling (added after a real accuracy gap was found) ---
Until this fix, get_concrete_factor_per_m3() ignored `grade` entirely
whenever cement_type was known (which is almost always, since the BOQ
classifier defaults to a cement type when the text doesn't state one) --
M10 and M40 concrete were priced IDENTICALLY. Verified directly: every
grade from M10 to M40 returned exactly 201.26 kgCO2e/m3 for PPC. That's
wrong -- higher grades genuinely use more cement per m3 and have a real,
higher GWP.

The fix reuses data that was already sitting in ice_db_factors.json
unused for this purpose: concrete.by_grade.cem_i is ICE v4.1's own
CEM-I-cement, by-M-grade curve. It isn't applied as an absolute value
(that would throw away IFC's India-specific calibration) -- it's used
only for its SHAPE: the ratio of a given grade's GWP to M40's GWP in
that same curve, applied multiplicatively on top of IFC's India-
specific, cement-type-based anchor. IFC's own concrete table (Table 14)
is itself calibrated to M40 composition, so this ratio is being applied
against the same grade basis on both sides -- not mixing an M40 IFC
number with an ICE M25 number as if they were already comparable.

A grade absent from the ratio table (or no grade given at all) falls
back to a scale factor of 1.0 -- i.e. the M40-equivalent value, same as
before this fix -- rather than guessing or erroring.
"""

from __future__ import annotations
from functools import lru_cache
import json
from pathlib import Path
from typing import Optional

FACTORS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "ice_db" / "ice_db_factors.json"
)

VALID_CEMENT_TYPES = ["OPC", "PSC", "PPC"]

# ICE v4.1's own CEM I grade curve is calibrated around M40 (its numbers
# run M10..M50), which lines up with IFC's concrete table also being an
# M40 calibration -- so M40 is the anchor grade for the ratio, not an
# arbitrary choice.
GRADE_SCALE_ANCHOR = "M40"

@lru_cache(maxsize=1)             # add this line directly above the function

def load_factors() -> dict:
    with open(FACTORS_PATH, "r") as f:
        return json.load(f)


def get_concrete_grade_scale_factor(grade: Optional[str]) -> float:
    """Ratio of ICE's CEM I per-kg GWP for `grade` vs its M40 value.
    Multiply IFC's India-specific cement-type anchor by this to
    differentiate other grades while keeping the absolute level India-
    calibrated -- see module docstring for why this is a ratio, not an
    absolute substitution.

    Returns 1.0 (no scaling -- the M40-equivalent value) when grade is
    missing or not one of ICE's tabulated grades, rather than guessing.
    """
    if not grade:
        return 1.0
    factors = load_factors()
    grade_table = factors["concrete"]["by_grade"]["cem_i"]
    anchor = grade_table.get(GRADE_SCALE_ANCHOR)
    val = grade_table.get(grade.upper())
    if anchor is None or val is None:
        return 1.0
    return val / anchor


# ---------------------------------------------------------------------------
# Concrete
# ---------------------------------------------------------------------------

def get_concrete_factor_ifc(cement_type: str) -> dict:
    """Primary lookup: IFC's real Indian ready-mix concrete data, by
    cement type. Returns the full entry (gwp_kgco2e_per_kg,
    energy_derived_fraction_of_gwp, display_name) since the caller
    (calculation_engine.py) needs the energy fraction for CEA adjustment,
    not just the raw factor.
    """
    factors = load_factors()
    entry = factors["ifc_india"]["concrete"]["by_cement_type"].get(cement_type.upper())
    if entry is None:
        raise ValueError(
            f"No IFC concrete factor for cement_type '{cement_type}' -- "
            f"valid types are {VALID_CEMENT_TYPES}"
        )
    return entry


def get_concrete_factor_per_m3_ifc(
    cement_type: str, grade: Optional[str] = None, apply_cea: bool = True
) -> float:
    """Returns kgCO2e per m3 of concrete using IFC's cement-type-based
    factor, optionally CEA-adjusted (see cea_adjustment.py) and grade-
    scaled (see get_concrete_grade_scale_factor -- module docstring has
    the full reasoning). This is the primary path -- use when cement_type
    is known.
    """
    from app.services.cea_adjustment import apply_cea_adjustment_ifc

    factors = load_factors()
    entry = get_concrete_factor_ifc(cement_type)
    density = factors["ifc_india"]["concrete"]["default_density_kg_per_m3"]

    per_kg = entry["gwp_kgco2e_per_kg"]
    if apply_cea:
        per_kg = apply_cea_adjustment_ifc(per_kg, entry["energy_derived_fraction_of_gwp"])

    per_kg *= get_concrete_grade_scale_factor(grade)

    return per_kg * density


def get_concrete_factor_per_m3_ice_fallback(
    grade: str, cement_type: str = "uk_average_cement"
) -> float:
    """FALLBACK ONLY: ICE's M-grade-based table, used when cement_type is
    unknown but M-grade is known. No CEA adjustment applied here -- the
    UK/EU grid baseline ICE assumed hasn't been extracted from ICE's own
    methodology docs, so adjusting without that denominator would mean
    fabricating a number. This is a stated, known gap, not an oversight.
    """
    factors = load_factors()
    grade_table = factors["concrete"]["by_grade"].get(cement_type)
    if grade_table is None:
        raise ValueError(f"Unknown ICE cement_type '{cement_type}'")
    per_kg = grade_table.get(grade)
    if per_kg is None:
        raise ValueError(f"No ICE factor for concrete grade '{grade}'")
    density = factors["concrete"]["default_density_kg_per_m3"]
    return per_kg * density


def get_concrete_factor_per_m3(
    cement_type: Optional[str] = None, grade: Optional[str] = None, apply_cea: bool = True
) -> tuple[float, str]:
    """Top-level concrete lookup. Prefers IFC (cement_type-based) when
    cement_type is available; falls back to ICE (grade-based) when it
    isn't. Grade is now used on BOTH paths -- as a scaling ratio on the
    IFC path, as the direct lookup key on the ICE fallback path -- see
    module docstring for why this changed. Returns (factor_per_m3,
    source_label) so callers can record which path was actually used.

    At least one of cement_type or grade must be provided.
    """
    if cement_type:
        return get_concrete_factor_per_m3_ifc(cement_type, grade=grade, apply_cea=apply_cea), "ifc_india"
    if grade:
        return get_concrete_factor_per_m3_ice_fallback(grade), "ice_fallback"
    raise ValueError("Must provide either cement_type or grade to look up a concrete factor")


# ---------------------------------------------------------------------------
# Steel
# ---------------------------------------------------------------------------

def get_steel_rebar_factor_ifc() -> dict:
    factors = load_factors()
    return factors["ifc_india"]["steel_rebar"]


def get_steel_rebar_factor_per_kg(apply_cea: bool = True) -> tuple[float, str]:
    """Primary: IFC's India-specific rebar factor (2.6 kgCO2e/kg),
    optionally CEA-adjusted. Returns (factor, source_label).
    """
    from app.services.cea_adjustment import apply_cea_adjustment_ifc

    entry = get_steel_rebar_factor_ifc()
    per_kg = entry["gwp_kgco2e_per_kg"]
    if apply_cea:
        per_kg = apply_cea_adjustment_ifc(per_kg, entry["energy_derived_fraction_of_gwp"])
    return per_kg, "ifc_india"


def get_steel_rebar_factor_per_kg_ice_fallback() -> float:
    """FALLBACK ONLY: ICE's world-average rebar figure. No CEA
    adjustment applied -- same reasoning as the concrete fallback above.
    """
    factors = load_factors()
    return factors["steel"]["rebar"]["value"]
