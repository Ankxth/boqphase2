"""THE single emission-factor source for both carbon pipelines --
Workstream 01 of the Foundation Plan ("lets make the emission factor
source to be from one source for both the wo upload and the excel
upload").

Before this module existed, boq_carbon/engine.py read placeholder-
quality numbers from boq_carbon_extra_factors.json (via extra_factors.py,
now a deprecated shim -- see that module), while wo_carbon/
wo_carbon_engine.py read a DIFFERENT, independently-sourced number
embedded directly on each of the 7,108 rows in
master_item_code_factors.json. For several categories that existed in
both places, the two numbers disagreed -- not because either was
fabricated, but because wo_carbon's copy had already been through the
CEA grid-factor adjustment (see cea_adjustment.py) and boq_carbon's had
not. Every one of those discrepancies was verified by reproducing
wo_carbon's number from boq_carbon's raw IFC figure + CEA adjustment --
see app/data/ice_db/emission_factors.json's per-category
"_reconciliation" notes for the exact before/after value and the
verification.

Two categories are deliberately NOT in emission_factors.json and are not
served by this module: concrete (rcc/pcc) and reinforcement steel. Both
depend on cement_type and/or grade, not just a flat per-category number,
so they don't fit this file's schema. They were already served from one
shared place before this workstream (app.services.ice_factors, reading
app/data/ice_db/ice_db_factors.json's ifc_india section) -- this module
re-exports thin wrappers for them anyway (get_concrete_factor_per_kg,
get_steel_rebar_factor_per_kg) purely so a caller can import "the
canonical factor source" from ONE module and get every material,
concrete/rebar included, without needing to know which of two files
actually backs which category.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Optional

FACTORS_PATH = Path(__file__).resolve().parent.parent / "data" / "ice_db" / "emission_factors.json"

# Categories handled by ice_factors.py instead -- listed here so a caller
# that accidentally asks this module for one of them gets a clear error
# pointing at the right place, rather than a bare KeyError.
_CONCRETE_REBAR_CATEGORIES = {"concrete", "rcc", "pcc", "steel_reinforcement"}


@lru_cache(maxsize=1)
def load_emission_factors() -> dict:
    with open(FACTORS_PATH, "r") as f:
        return json.load(f)


def get_factor(category: str) -> dict:
    """Returns the full canonical factor entry for `category` (structural_steel,
    aluminium, glass, brickwork, blockwork_aac, blockwork_dense,
    plaster_cement, plaster_gypsum, tile_ceramic, tile_vitrified,
    natural_stone, paint, timber_wood, and the wo_carbon-only categories
    -- sand, aggregate, cement_bagged, cement_mortar, insulation_*,
    waterproofing, copper, pvc_pipe_fitting, bitumen_asphalt,
    steel_gi_galvanized, steel_stainless, upvc_window_door_frame).

    Raises KeyError for an unknown category, ValueError for concrete/
    steel_reinforcement (see module docstring -- use
    get_concrete_factor_per_kg / get_steel_rebar_factor_per_kg instead).
    """
    if category in _CONCRETE_REBAR_CATEGORIES:
        raise ValueError(
            f"'{category}' is cement-type/grade-dependent, not a flat category factor -- "
            f"use get_concrete_factor_per_kg() or get_steel_rebar_factor_per_kg() instead."
        )
    factors = load_emission_factors()
    entry = factors.get(category)
    if entry is None:
        raise KeyError(f"No canonical emission factor for category '{category}'")
    return entry


def get_ef_kgco2e_per_kg(category: str) -> float:
    """Convenience accessor -- just the resolved, already-CEA-adjusted-
    where-applicable kgCO2e/kg number for `category`."""
    return get_factor(category)["ef_kgco2e_per_kg"]


# ---------------------------------------------------------------------------
# Concrete / reinforcement steel -- thin re-exports, see module docstring
# ---------------------------------------------------------------------------

def get_concrete_factor_per_kg(
    cement_type: Optional[str] = None, grade: Optional[str] = None, apply_cea: bool = True
) -> tuple[float, str]:
    """Per-KG concrete factor (the per-m3 ice_factors.py function divided
    by the shared density constant) -- convenient for wo_carbon, which
    works in per-kg terms throughout. Returns (factor_per_kg,
    source_label)."""
    from app.services.ice_factors import get_concrete_density_kg_per_m3, get_concrete_factor_per_m3

    per_m3, source = get_concrete_factor_per_m3(cement_type=cement_type, grade=grade, apply_cea=apply_cea)
    return per_m3 / get_concrete_density_kg_per_m3(), source


def get_steel_rebar_factor_per_kg(apply_cea: bool = True) -> tuple[float, str]:
    from app.services.ice_factors import get_steel_rebar_factor_per_kg as _get_rebar

    return _get_rebar(apply_cea=apply_cea)


def detect_cement_type(text: str) -> Optional[str]:
    """Shared cement-type detector -- re-exports boq_carbon/classifier.py's
    own compiled regexes (not a re-implementation) so wo_carbon can apply
    the exact same detection logic to a master-file Activity Code's own
    `desc` text, with zero risk of the two patterns drifting apart.
    Returns None (caller should default to PPC, same as classifier.py's
    own documented default) when no cement-type keyword is present.
    """
    from app.services.boq_carbon.classifier import (
        CEMENT_TYPE_OPC, CEMENT_TYPE_PPC, CEMENT_TYPE_PSC,
        _CEMENT_TYPE_OPC_RE, _CEMENT_TYPE_PPC_RE, _CEMENT_TYPE_PSC_RE,
    )

    if _CEMENT_TYPE_PSC_RE.search(text):
        return CEMENT_TYPE_PSC
    if _CEMENT_TYPE_PPC_RE.search(text):
        return CEMENT_TYPE_PPC
    if _CEMENT_TYPE_OPC_RE.search(text):
        return CEMENT_TYPE_OPC
    return None


def detect_grade(text: str) -> Optional[str]:
    """Shared concrete-grade detector -- re-exports boq_carbon/
    classifier.py's own compiled _GRADE_RE (not a re-implementation).
    Returns e.g. "M30", or None if no grade token is present.
    """
    from app.services.boq_carbon.classifier import _GRADE_RE

    m = _GRADE_RE.search(text)
    return f"M{m.group(1)}" if m else None