"""CEA grid-factor adjustment for IFC-sourced material emission factors.

Methodology: split a material's GWP into process emissions (unaffected
by grid electricity -- e.g. cement calcination, a chemical reaction)
and energy-derived emissions (electricity + fuel combustion, which DOES
depend on grid cleanliness). Only the energy-derived portion is rescaled,
using the ratio of the current CEA grid factor to the grid factor
implicitly embedded in the IFC report's own modeling data.

adjusted = process_portion + energy_portion * (current_grid_factor / baseline_grid_factor)

Where:
- process_portion = gwp * (1 - energy_derived_fraction_of_gwp)
- energy_portion   = gwp * energy_derived_fraction_of_gwp

This ONLY applies to ifc_india-sourced factors (concrete by cement type,
steel rebar) -- see ice_db_factors.json's "ifc_india" section for the
energy_derived_fraction values this reads. It is deliberately NOT applied
to the ICE fallback table (uk_average_cement/cem_i M-grade factors),
because that would require the UK/EU grid baseline ICE itself assumed,
which has not been extracted from ICE's own methodology documentation.
Rather than guess at that number, ICE fallback factors are left
unadjusted -- a stated gap, not a silent omission.

Baseline grid factor caveat: IFC's embedded assumption is dated to ~2012
generation data. CEA's published series doesn't extend back that far --
FY2013-14 (0.774 tCO2/MWh) is used as the nearest available approximation,
not an exact 2012 match. See ice_db_factors.json's "cea" section for the
full note.
"""

from __future__ import annotations
from functools import lru_cache
import json
from pathlib import Path

FACTORS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "ice_db" / "ice_db_factors.json"
)

@lru_cache(maxsize=1) 
def _load_cea_data() -> dict:
    with open(FACTORS_PATH, "r") as f:
        return json.load(f)["cea"]


def apply_cea_adjustment_ifc(gwp_kgco2e_per_kg: float, energy_derived_fraction_of_gwp: float) -> float:
    """Applies the CEA grid-factor adjustment to a single IFC-sourced
    factor. energy_derived_fraction_of_gwp comes from the material's own
    entry in ice_db_factors.json (e.g. 0.016 for OPC concrete, 0.7538
    for steel rebar) -- it is NOT a constant, it's specific to each
    material, since different materials have very different splits
    between process and energy emissions.
    """
    cea = _load_cea_data()
    current = cea["current_grid_factor"]
    baseline = cea["baseline_grid_factor"]

    process_portion = gwp_kgco2e_per_kg * (1 - energy_derived_fraction_of_gwp)
    energy_portion = gwp_kgco2e_per_kg * energy_derived_fraction_of_gwp

    adjusted_energy_portion = energy_portion * (current / baseline)

    return process_portion + adjusted_energy_portion


def get_cea_adjustment_summary() -> dict:
    """Returns the current CEA grid factors in use, for display/debugging
    -- e.g. to show in the dashboard which CEA database version and
    baseline year an adjustment was computed against.
    """
    cea = _load_cea_data()
    return {
        "current_grid_factor": cea["current_grid_factor"],
        "current_grid_factor_year": cea["current_grid_factor_year"],
        "baseline_grid_factor": cea["baseline_grid_factor"],
        "baseline_grid_factor_year": cea["baseline_grid_factor_year"],
        "adjustment_ratio": cea["current_grid_factor"] / cea["baseline_grid_factor"],
    }