"""DEPRECATED as of Workstream 01 (one emission-factor source) -- no
engine imports this module anymore. Kept only as a historical/backward-
compatible shim so nothing that might still import `get_factor` from
here breaks outright; it now delegates to app.services.emission_factors,
the real canonical source.

boq_carbon_extra_factors.json (this module's original data file) is
still on disk, UNCHANGED, as the historical record of the original
placeholder-quality figures and their full sourcing writeups (several of
those writeups -- the by-product-form breakdowns, the EPD cross-checks --
are longer than what got carried into emission_factors.json's entries,
which quote the resolved number and a summary rather than repeating the
full provenance essay). It is simply no longer read at calculation time.

See app/services/emission_factors.py's module docstring for the full
story of what changed and why.
"""

from __future__ import annotations

import warnings

from app.services.emission_factors import get_factor as _get_canonical_factor

# category name in THIS module's old vocabulary -> canonical name in
# emission_factors.json ("structural_steel" was already boq_carbon's own
# name and needed no rename; wo_carbon's master file used the reversed
# "steel_structural"/"steel_reinforcement" convention and was the one
# renamed instead, since boq_carbon's naming already matched Phase 1's
# boq_extractor.py -- see the Workstream 01 reconciliation log).
_LEGACY_NAME_MAP = {
    "brick_clay": "brickwork",
    "aac_block": "blockwork_aac",
    "cement_plaster": "plaster_cement",
    "ceramic_tile": "tile_ceramic",
    "timber": "timber_wood",
}


def get_factor(category: str) -> dict:
    warnings.warn(
        "app.services.boq_carbon.extra_factors.get_factor() is deprecated -- "
        "use app.services.emission_factors.get_factor() instead (Workstream 01).",
        DeprecationWarning,
        stacklevel=2,
    )
    canonical_name = _LEGACY_NAME_MAP.get(category, category)
    return _get_canonical_factor(canonical_name)