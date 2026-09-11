"""Emission factors for the material categories ice_db_factors.json
doesn't cover yet (everything except concrete and reinforcement steel).

See boq_carbon_extra_factors.json's own "_status"/"_note" fields --
these are placeholder assumptions, not yet verified the rigorous way
concrete/steel were. Kept in a separate file/module rather than added
into ice_db_factors.json directly, so Phase 1's existing, already-
verified data file is never touched by Phase 2 work -- this file is
purely additive.
"""

from __future__ import annotations
from functools import lru_cache


import json
from pathlib import Path

FACTORS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ice_db" / "boq_carbon_extra_factors.json"

@lru_cache(maxsize=1) 
def load_extra_factors() -> dict:
    with open(FACTORS_PATH, "r") as f:
        return json.load(f)


def get_factor(category: str) -> dict:
    """Returns the raw factor entry for a non-concrete/non-rebar
    category (structural_steel, brick_clay, aac_block, cement_plaster,
    ceramic_tile, paint, aluminium, glass). Raises KeyError if unknown.
    """
    factors = load_extra_factors()
    entry = factors.get(category)
    if entry is None:
        raise KeyError(f"No extra factor entry for category '{category}'")
    return entry