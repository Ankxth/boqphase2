"""Canonical project data model.

This is the single shape every part of the pipeline reads from and writes
into -- the tiered form, the BOQ-matching step, the LLM fallback, and the
calculation engine all operate on this schema, never on raw form data.

Every field is wrapped in a FieldValue, which tracks not just the value
but where it came from and how confident we are in it:

- source: "user-entered"       -> the person typed it in directly
          "boq-matched"        -> scaled from a REFERENCE project's BOQ
                                   (e.g. Botanico/Ecopolitan), via
                                   boq_match.py
          "own-boq-extracted"  -> extracted from THIS project's OWN BOQ,
                                   once one becomes available later in
                                   design (Phase C) -- outranks
                                   boq-matched, since it's this project's
                                   real data, not a borrowed proxy
          "llm-estimated"      -> filled in by the LLM fallback when
                                   nothing else was available
          "unset"              -> not filled in yet (only valid for
                                   optional fields)

- confidence: 0.0-1.0, used by the frontend's review step to decide how a
  field gets highlighted (e.g. LLM-estimated fields shown in amber so the
  user knows to double check them). Rough scale in use across the
  pipeline: own-boq-extracted 0.9, boq-matched 0.6, llm-estimated 0.4,
  user-entered 1.0.
"""

from __future__ import annotations

from enum import Enum
from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

FieldSource = Literal["user-entered", "boq-matched", "own-boq-extracted", "llm-estimated", "unset"]


class FieldValue(BaseModel, Generic[T]):
    """Wraps a single data point with its provenance."""
    value: Optional[T] = None
    source: FieldSource = "unset"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Enums (category, or ENUM = a fixed list of allowed values) for fields with
# a fixed set of valid options
# ---------------------------------------------------------------------------

class StructuralSystemType(str, Enum):
    rcc_frame = "rcc_frame"                    # reinforced cement concrete frame
    load_bearing_masonry = "load_bearing_masonry"
    steel_frame = "steel_frame"
    composite = "composite"


class Typology(str, Enum):
    residential = "residential"
    commercial = "commercial"
    institutional = "institutional"
    mixed_use = "mixed_use"


class FoundationType(str, Enum):
    isolated_footing = "isolated_footing"
    raft = "raft"
    pile = "pile"
    combined_footing = "combined_footing"


class FinishSpecLevel(str, Enum):
    economical = "economical"
    standard = "standard"
    premium = "premium"


class MepComplexity(str, Enum):
    basic = "basic"
    standard = "standard"
    complex = "complex"


class SiteCondition(str, Enum):
    normal_soil = "normal_soil"
    rocky = "rocky"
    waterlogged = "waterlogged"
    reclaimed_land = "reclaimed_land"


class CementType(str, Enum):
    """Maps directly to IFC's India-specific concrete factors (see
    ice_factors.py) -- OPC (ordinary Portland), PSC (25% GGBS slag
    blend), PPC (30% fly ash blend)."""
    opc = "OPC"
    psc = "PSC"
    ppc = "PPC"


# ---------------------------------------------------------------------------
# Tier blocks
# ---------------------------------------------------------------------------

class MandatoryFields(BaseModel):
    gfa_sqm: FieldValue[float] = FieldValue()          # gross floor area, always stored in sqm internally
    location: FieldValue[str] = FieldValue()           # city/state, or "lat,long"
    structural_system_type: FieldValue[StructuralSystemType] = FieldValue()


class Tier2Fields(BaseModel):
    typology: FieldValue[Typology] = FieldValue()
    num_floors: FieldValue[int] = FieldValue()
    has_basement: FieldValue[bool] = FieldValue()
    basement_count: FieldValue[int] = FieldValue()
    foundation_type: FieldValue[FoundationType] = FieldValue()
    finish_spec_level: FieldValue[FinishSpecLevel] = FieldValue()
    parking_type: FieldValue[str] = FieldValue()       # e.g. "surface", "basement", "multi-level"
    parking_area_sqm: FieldValue[float] = FieldValue()


class Tier3Fields(BaseModel):
    concrete_grade_mix: FieldValue[str] = FieldValue()      # e.g. "M30", "M35" -- used only as ICE fallback when cement_type is unknown
    cement_type: FieldValue[CementType] = FieldValue()      # primary concrete-factor lookup key -- see ice_factors.py
    steel_reinforcement_ratio_kg_per_sqm: FieldValue[float] = FieldValue()
    facade_type: FieldValue[str] = FieldValue()
    glazing_pct: FieldValue[float] = FieldValue()           # 0-100
    mep_complexity: FieldValue[MepComplexity] = FieldValue()
    green_cert_target: FieldValue[str] = FieldValue()       # e.g. "GRIHA 3-star", "none"
    site_condition: FieldValue[SiteCondition] = FieldValue()


# ---------------------------------------------------------------------------
# Top-level project schema
# ---------------------------------------------------------------------------

class ProjectSchema(BaseModel):
    """The single unified object passed between every pipeline stage."""
    project_id: str
    # Workstream 04: which company this project belongs to -- decides
    # where it's persisted (app/services/company_store.py) and which
    # company's reference projects boq_match.py is allowed to learn
    # from. Defaults to "provident" (kept as a literal here rather than
    # importing app.services.company_store.DEFAULT_COMPANY_ID, so this
    # schema module doesn't take a dependency on the services layer --
    # the two must be kept in sync, and company_store.py's own docstring
    # says so). A project loaded from a pre-Workstream-04 JSON file
    # (which has no company_id key at all) picks up this same default
    # automatically, which is exactly the intended migration behavior:
    # every project that existed before this field did belongs to
    # Provident.
    company_id: str = "provident"
    mandatory: MandatoryFields = MandatoryFields()
    tier2: Tier2Fields = Tier2Fields()
    tier3: Tier3Fields = Tier3Fields()

    def completeness(self) -> dict[str, float]:
        """Rough fraction of filled (non-'unset') fields per tier --
        useful for showing the user how much detail they've provided."""
        def frac(block: BaseModel) -> float:
            fields = block.model_dump().values()
            total = len(fields)
            filled = sum(1 for f in fields if f.get("source") != "unset")
            return filled / total if total else 0.0

        return {
            "mandatory": frac(self.mandatory),
            "tier2": frac(self.tier2),
            "tier3": frac(self.tier3),
        }