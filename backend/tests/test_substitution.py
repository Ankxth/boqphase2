"""Tests for app/services/substitution.py (Phase 1 substitution
suggestions). No pytest coverage existed for this module before
Workstream 08 -- it had only ever been exercised manually via
scripts/test_full_pipeline.py. Added now because Workstream 08 changes
this exact module (a new, third suggestion type) and
app/services/calculation_engine.py (the new steel_factor_override
parameter it depends on); this is the discipline the roadmap's own
"carry the golden-file discipline forward" recommendation calls for --
new computed logic gets tests from the start, not added retroactively.

Every assertion about savings_kg here is a real recompute cross-check
(see test_combined_impact_matches_independent_manual_recompute), not a
hardcoded golden figure -- consistent with substitution.py's own
docstring: "the real computed number," never an estimate.
"""

from __future__ import annotations

import pytest

from app.schemas.project_schema import CementType, FieldValue, ProjectSchema, StructuralSystemType
from app.services.calculation_engine import calculate_embodied_carbon
from app.services.substitution import (
    SUPPLIER_STEEL_FACTOR_PSEUDO_FIELD,
    compute_combined_impact,
    suggest_substitutions,
)
from app.services.supplier_catalog import get_entry


def _project(cement_type=CementType.opc, steel_ratio=110.0, num_floors=20, gfa=50000.0):
    p = ProjectSchema(project_id="ws08-substitution-test")
    p.mandatory.gfa_sqm = FieldValue(value=gfa, source="user-entered", confidence=1.0)
    p.mandatory.structural_system_type = FieldValue(
        value=StructuralSystemType.rcc_frame, source="user-entered", confidence=1.0
    )
    if num_floors is not None:
        p.tier2.num_floors = FieldValue(value=num_floors, source="user-entered", confidence=1.0)
    if cement_type is not None:
        p.tier3.cement_type = FieldValue(value=cement_type, source="user-entered", confidence=1.0)
    if steel_ratio is not None:
        p.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(
            value=steel_ratio, source="user-entered", confidence=1.0
        )
    return p


# --- Pre-existing suggestion types (no pytest coverage before this workstream) ---


def test_cement_swap_suggested_when_not_on_ppc():
    p = _project(cement_type=CementType.opc, steel_ratio=None, num_floors=None)
    result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, result)
    cement = [s for s in suggestions if s.field == "tier3.cement_type"]
    assert len(cement) == 1
    assert cement[0].current_value == "OPC"
    assert cement[0].suggested_value == "PPC"
    assert cement[0].savings_kg > 0
    assert cement[0].requires_engineering_review is False


def test_no_cement_swap_when_already_on_ppc():
    p = _project(cement_type=CementType.ppc, steel_ratio=None, num_floors=None)
    result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, result)
    assert [s for s in suggestions if s.field == "tier3.cement_type"] == []


def test_steel_ratio_reduction_suggested_above_band_and_flagged_for_review():
    # high_rise band is (100, 130) -- 110 is above the low end.
    p = _project(cement_type=None, steel_ratio=110.0, num_floors=20)
    result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, result)
    ratio = [s for s in suggestions if s.field == "tier3.steel_reinforcement_ratio_kg_per_sqm"]
    assert len(ratio) == 1
    assert ratio[0].requires_engineering_review is True
    assert ratio[0].savings_kg > 0


def test_no_steel_ratio_suggestion_when_already_at_low_end():
    p = _project(cement_type=None, steel_ratio=100.0, num_floors=20)  # low end of high_rise band
    result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, result)
    assert [s for s in suggestions if s.field == "tier3.steel_reinforcement_ratio_kg_per_sqm"] == []


# --- Workstream 08: supplier material swap ---


def test_supplier_steel_swap_suggested_and_matches_catalog_entry():
    p = _project(cement_type=None, steel_ratio=110.0, num_floors=None)
    result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, result)
    swaps = [s for s in suggestions if s.field == SUPPLIER_STEEL_FACTOR_PSEUDO_FIELD]
    assert len(swaps) == 1
    swap = swaps[0]

    ars = get_entry("steel_ifc_to_ars_eaf_recycled")
    assert swap.override_factor_kgco2e_per_kg == ars["substitute_gwp_kgco2e_per_kg_fixed"]
    assert swap.supplier == "ARS Steels and Alloy International Pvt Ltd"
    assert swap.evidence_tier == "supplier_epd_verified"
    # Reinforcement steel is structural by definition -- always flagged,
    # unlike the cement swap above.
    assert swap.requires_engineering_review is True
    assert swap.savings_kg > 0
    # savings_pct is stored rounded to 2 decimals (see _suggest_supplier_steel_swap) -- compare at that precision.
    assert swap.savings_pct == pytest.approx((swap.savings_kg / swap.carbon_kg_before) * 100, abs=0.01)


def test_supplier_steel_swap_absent_when_no_steel_quantity_basis():
    p = _project(cement_type=None, steel_ratio=None, num_floors=None)
    result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, result)
    assert [s for s in suggestions if s.field == SUPPLIER_STEEL_FACTOR_PSEUDO_FIELD] == []


def test_supplier_steel_swap_not_suggested_when_catalog_factor_is_not_actually_lower(monkeypatch):
    """If a future catalog entry's fixed factor isn't actually below the
    project's current effective factor, it must not be suggested as a
    "savings" -- see supplier_catalog.list_fixed_factor_alternatives_for_category's
    caller-side filter in _suggest_supplier_steel_swap."""
    import app.services.substitution as substitution_module
    from app.services.supplier_catalog import SupplierAlternative

    worse_alt = SupplierAlternative(
        id="fake_worse_supplier",
        category="reinforcement_steel",
        product_name="Fake higher-carbon product",
        supplier="Fake Supplier Ltd",
        region="Nowhere",
        evidence_tier="supplier_epd_verified",
        source="test fixture",
        basis="fixed_factor_per_kg",
        fixed_gwp_kgco2e_per_kg=999.0,  # deliberately absurdly high
        max_recommended_pct=100,
        structural_caveat="n/a",
        reasoning="n/a",
    )
    monkeypatch.setattr(
        substitution_module, "list_fixed_factor_alternatives_for_category", lambda category: [worse_alt]
    )

    p = _project(cement_type=None, steel_ratio=110.0, num_floors=None)
    result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, result)
    assert [s for s in suggestions if s.field == SUPPLIER_STEEL_FACTOR_PSEUDO_FIELD] == []


# --- Workstream 08: combining the supplier swap with the pre-existing suggestions ---


def test_combined_impact_matches_independent_manual_recompute():
    """The core correctness check for this workstream: applying all three
    suggestion types together via compute_combined_impact() must produce
    EXACTLY the same total as manually cloning the project, applying all
    three changes by hand, and calling calculate_embodied_carbon() once
    directly -- proving the pseudo-field handling added for the supplier
    swap doesn't silently diverge from a real, independent recompute.
    """
    p = _project(cement_type=CementType.opc, steel_ratio=110.0, num_floors=20)
    actual_result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, actual_result)
    assert len(suggestions) == 3  # cement swap + steel ratio + supplier swap all apply here

    combined = compute_combined_impact(p, actual_result, suggestions)
    assert combined is not None
    assert combined.requires_engineering_review is True  # steel ratio + supplier swap both require it

    manual = p.model_copy(deep=True)
    manual.tier3.cement_type = FieldValue(value=CementType.ppc, source="user-entered", confidence=1.0)
    manual.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(
        value=100.0, source="user-entered", confidence=1.0
    )  # low end of the high_rise band
    ars = get_entry("steel_ifc_to_ars_eaf_recycled")
    manual_result = calculate_embodied_carbon(
        manual, steel_factor_override_kgco2e_per_kg=ars["substitute_gwp_kgco2e_per_kg_fixed"]
    )

    assert combined.carbon_kg_after_all_applied == pytest.approx(manual_result.total_carbon_kg, rel=1e-12)
    assert combined.carbon_kg_before == pytest.approx(actual_result.total_carbon_kg, rel=1e-12)


def test_combined_impact_with_only_supplier_swap_equals_that_suggestions_own_savings():
    p = _project(cement_type=CementType.ppc, steel_ratio=110.0, num_floors=20)  # already on PPC -- no cement suggestion
    actual_result = calculate_embodied_carbon(p)
    suggestions = suggest_substitutions(p, actual_result)
    swap_only = [s for s in suggestions if s.field == SUPPLIER_STEEL_FACTOR_PSEUDO_FIELD]
    ratio_only = [s for s in suggestions if s.field == "tier3.steel_reinforcement_ratio_kg_per_sqm"]
    assert len(swap_only) == 1

    combined_swap_alone = compute_combined_impact(p, actual_result, swap_only)
    assert combined_swap_alone.total_savings_kg == pytest.approx(swap_only[0].savings_kg, rel=1e-9)

    # And combining it with the ratio suggestion too should be strictly
    # more savings than either alone (independent multiplicative terms).
    combined_both = compute_combined_impact(p, actual_result, swap_only + ratio_only)
    assert combined_both.total_savings_kg > combined_swap_alone.total_savings_kg


# --- calculate_embodied_carbon()'s new override parameter, directly ---


def test_calculate_embodied_carbon_steel_override_matches_manual_multiplication():
    p = _project(cement_type=None, steel_ratio=80.0, num_floors=None)
    override_factor = 0.592
    result = calculate_embodied_carbon(p, steel_factor_override_kgco2e_per_kg=override_factor)
    steel_item = next(b for b in result.breakdown if b.material.startswith("Reinforcement steel"))
    assert steel_item.factor_used == override_factor
    assert steel_item.factor_source == "supplier_epd_fixed"
    assert steel_item.carbon_kg == pytest.approx(steel_item.quantity * override_factor, rel=1e-12)


def test_calculate_embodied_carbon_default_behavior_unchanged_when_override_omitted():
    p = _project(cement_type=None, steel_ratio=80.0, num_floors=None)
    with_default_call = calculate_embodied_carbon(p)
    with_explicit_none = calculate_embodied_carbon(p, steel_factor_override_kgco2e_per_kg=None)
    assert with_default_call.total_carbon_kg == with_explicit_none.total_carbon_kg
    steel_item = next(b for b in with_default_call.breakdown if b.material.startswith("Reinforcement steel"))
    assert steel_item.factor_source == "ifc_india"
    assert steel_item.material == "Reinforcement steel (rebar)"  # no override suffix appended