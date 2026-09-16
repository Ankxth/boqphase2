"""Workstream 08: the ONE shared supplier/material-substitution data
layer -- Phase 1 (app/services/substitution.py), Phase 2
(app/services/boq_carbon/substitution_engine.py), and any future Phase 3
chatbot tool surface all read alternatives through this module, per the
roadmap's "From static catalog to supplier recommendation" design
direction: "Introduce one shared data layer... Phase 1, Phase 2, and the
Phase 3 chatbot all read from this one catalog instead of maintaining
separate substitution logic."

Deliberate scope decision, stated plainly: this is a structured,
versioned catalog you and your team populate and update (EPDs, supplier
declarations, IS-code specification choices) -- NOT a live supplier-API
integration. Getting the schema right now means a future live
integration can slot in later without touching any of the code that
reads from this module. See the roadmap's own note on this.

Why this module reads the existing app/data/ice_db/substitution_catalog.json
rather than a brand-new file: that file is already, factually, a sourced
catalog of material alternatives with product identity, evidence tiers,
and citations -- Workstream 07 already disclosed exactly which sources
were checked and rejected (see its own "evidence_log"). Forking a second,
parallel JSON file with the same substance under a new name would mean
maintaining two catalogs that can drift apart, which is precisely the
failure mode this workstream exists to avoid. What was missing was not a
second file -- it was ONE shared Python access layer, and explicit
supplier/region fields on each entry (added this workstream) so a
consumer doesn't have to re-parse free text out of 'source' or
'requires_supplier_match' to know who makes something and where.

Two ways to read the catalog, kept both because each existing consumer
needs a different shape:

- `load_catalog()` / `get_entry()` / `list_entries_for_category()` --
  the raw dict shape Phase 2's substitution_engine.py already depends on
  (base_category, substitute_cement_type / substitute_category /
  substitute_gwp_kgco2e_per_kg_fixed, max_recommended_pct, ...). Kept
  byte-for-byte compatible with the pre-Workstream-08 loader in
  boq_carbon/substitution_catalog.py (now a thin delegator to this
  module) so nothing that already reads the catalog this way needs to
  change.

- `list_alternatives_for_category()` -- a new, uniform
  `SupplierAlternative` view (product name, supplier, region, evidence
  tier, sourced reasoning) that doesn't require the caller to know
  which of the three substitute_* mechanisms a given entry uses. This is
  what Workstream 08's new Phase 1 supplier-steel suggestion reads (see
  substitution.py), and what a future chatbot tool ("what green
  alternatives exist for reinforcement_steel?") should read too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "ice_db" / "substitution_catalog.json"


class SupplierAlternative(BaseModel):
    id: str
    category: str
    product_name: str
    # None for a generic IS-code material specification available from many
    # producers (e.g. a PSC/PPC cement blend, AAC block) -- not every real,
    # sourced alternative is tied to one named company, and inventing a
    # supplier name for those would be less honest than leaving it unset.
    supplier: Optional[str] = None
    region: Optional[str] = None
    evidence_tier: str
    source: str
    # "recompute_via_engine": the alternative is applied by re-running the
    # real calculation engine with a changed cement_type/category (no
    # standalone per-kg figure to quote on its own).
    # "fixed_factor_per_kg": the alternative carries its own already-sourced
    # per-kg GWP figure (e.g. a supplier's verified EPD), applied directly
    # rather than through the engine's CEA-adjusted default path -- see
    # substitution_engine.py's own comment on why CEA is deliberately NOT
    # re-applied on top of an already-real, already-declared figure.
    basis: str
    fixed_gwp_kgco2e_per_kg: Optional[float] = None
    max_recommended_pct: float
    requires_engineering_review_above_max: bool = False
    always_requires_review_if_load_bearing: bool = False
    structural_caveat: str
    reasoning: str


def load_catalog() -> list[dict]:
    with open(CATALOG_PATH, "r") as f:
        data = json.load(f)
    return data["substitutions"]


def get_entry(substitution_id: str) -> Optional[dict]:
    for entry in load_catalog():
        if entry["id"] == substitution_id:
            return entry
    return None


def list_entries_for_category(category: str) -> list[dict]:
    """Raw catalog entries whose base_category matches -- the shape
    Phase 2's substitution_engine.py already consumes."""
    return [e for e in load_catalog() if e["base_category"] == category]


def list_categories() -> list[str]:
    """Distinct categories the catalog currently has at least one
    alternative for -- useful for a frontend or a future chatbot tool
    surface to know what's askable without hardcoding the list."""
    seen: list[str] = []
    for e in load_catalog():
        if e["base_category"] not in seen:
            seen.append(e["base_category"])
    return seen


def _to_alternative(entry: dict) -> SupplierAlternative:
    if "substitute_gwp_kgco2e_per_kg_fixed" in entry:
        basis = "fixed_factor_per_kg"
        fixed = entry["substitute_gwp_kgco2e_per_kg_fixed"]
    else:
        basis = "recompute_via_engine"
        fixed = None

    return SupplierAlternative(
        id=entry["id"],
        category=entry["base_category"],
        product_name=entry.get("substitute_label", entry["id"]),
        supplier=entry.get("supplier"),
        region=entry.get("region"),
        evidence_tier=entry.get("evidence_tier", "unspecified"),
        source=entry["source"],
        basis=basis,
        fixed_gwp_kgco2e_per_kg=fixed,
        max_recommended_pct=entry["max_recommended_pct"],
        requires_engineering_review_above_max=entry.get("requires_engineering_review_above_max", False),
        always_requires_review_if_load_bearing=entry.get("always_requires_review_if_load_bearing", False),
        structural_caveat=entry["structural_caveat"],
        reasoning=entry["reasoning"],
    )


def list_alternatives_for_category(category: str) -> list[SupplierAlternative]:
    """The uniform, engine-agnostic view: every sourced alternative
    currently in the catalog for `category`, regardless of whether it's
    applied via a cement-type swap, a category swap, or a fixed supplier
    EPD factor. Phase 1's new supplier-steel suggestion (see
    substitution.py) and any future chatbot tool surface should read the
    catalog through this function, not the raw dict functions above.
    """
    return [_to_alternative(e) for e in list_entries_for_category(category)]


def list_fixed_factor_alternatives_for_category(category: str) -> list[SupplierAlternative]:
    """Just the subset with their own standalone, already-sourced
    per-kg GWP figure (basis == "fixed_factor_per_kg") -- the only kind
    Phase 1 can currently apply, since Phase 1's calculation_engine.py
    works in per-kg/per-m3 factors on a whole-project basis, not
    per-line-item categories the way Phase 2's BOQ engine does. A
    "recompute_via_engine" entry (e.g. a cement-type swap) doesn't need
    this catalog to be applied in Phase 1 -- calculation_engine.py
    already supports switching cement_type directly and recomputing
    through the real IFC-sourced factor for every type, which is more
    general than replaying one hardcoded catalog pairing.
    """
    return [a for a in list_alternatives_for_category(category) if a.basis == "fixed_factor_per_kg"]