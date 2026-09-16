"""LLM-based fallback fill for Tier 2 / Tier 3 fields that are still
"unset" after BOQ matching.

Calls through app.services.llm_client, which routes to either a local
Ollama server or the Groq API depending on LLM_PROVIDER in .env.

Enum coercion: fields backed by an Enum in the schema (typology,
foundation_type, finish_spec_level, mep_complexity, site_condition,
cement_type) are explicitly coerced into real enum members here, not
left as raw strings. This matters because FieldValue assignment doesn't
go through Pydantic's validate_assignment (not enabled on the schema),
so simply setting FieldValue(value="pile", ...) on a field typed
FieldValue[FoundationType] silently stores the plain string, not a
FoundationType.pile member -- confirmed in testing: this produced both
Pydantic serializer warnings (harmless on its own) AND, for cement_type
specifically, a real crash in calculation_engine.py before that was
patched defensively. Coercing explicitly here fixes the actual cause
instead of handling it field-by-field wherever it happens to bite.

A value the LLM returns that ISN'T a valid member of its enum at all
(confirmed happening in testing: 'medium' for finish_spec_level, which
only has economical/standard/premium; 'urban' for site_condition, which
only has normal_soil/rocky/waterlogged/reclaimed_land) is dropped with a
printed warning, same treatment as an invalid concrete grade -- left
unset rather than silently stored as something that isn't a real option.

If the LLM call fails for any reason, falls back to simple hardcoded
defaults so the pipeline can still be tested end-to-end. Filled fields
are tagged source="llm-estimated", confidence 0.4.

Numeric estimates are clamped to plausible Indian-construction ranges
after the LLM call -- small models don't reliably know domain
conventions. Clamping doesn't fix a bad guess into a good one -- it just
prevents an implausible number from silently flowing into the
calculation engine.
"""

from __future__ import annotations

import json
from typing import Optional

from app.schemas.project_schema import (
    CementType,
    FieldValue,
    FinishSpecLevel,
    FoundationType,
    MepComplexity,
    ProjectSchema,
    SiteCondition,
    Typology,
)
from app.services import company_history
from app.services.llm_client import LLMUnavailableError, chat_json

LLM_ESTIMATED_CONFIDENCE = 0.4  # lower than boq-matched (0.6) -- generic guess, not comparable-project data

TIER2_FIELD_NAMES = [
    "typology", "num_floors", "has_basement", "basement_count",
    "foundation_type", "finish_spec_level", "parking_type", "parking_area_sqm",
]
TIER3_FIELD_NAMES = [
    "concrete_grade_mix", "cement_type", "steel_reinforcement_ratio_kg_per_sqm",
    "facade_type", "glazing_pct", "mep_complexity", "green_cert_target", "site_condition",
]

NUMERIC_RANGES = {
    "tier2.num_floors": (1, 60),
    "tier2.basement_count": (0, 4),
    "tier2.parking_area_sqm": (0, None),
    "tier3.steel_reinforcement_ratio_kg_per_sqm": (50, 130),
    "tier3.glazing_pct": (0, 100),
}

VALID_CONCRETE_GRADES = ["M10", "M15", "M20", "M25", "M30", "M35", "M40", "M45", "M50"]

# Fields backed by an Enum in the schema -- values for these get coerced
# to real enum members (or dropped, if invalid) rather than left as
# plain strings. See module docstring for why this matters.
ENUM_FIELD_TYPES = {
    "tier2.typology": Typology,
    "tier2.foundation_type": FoundationType,
    "tier2.finish_spec_level": FinishSpecLevel,
    "tier3.mep_complexity": MepComplexity,
    "tier3.site_condition": SiteCondition,
    "tier3.cement_type": CementType,
}


def _unset_fields(project: ProjectSchema) -> list[str]:
    unset = []
    for name in TIER2_FIELD_NAMES:
        if getattr(project.tier2, name).source == "unset":
            unset.append(f"tier2.{name}")
    for name in TIER3_FIELD_NAMES:
        if getattr(project.tier3, name).source == "unset":
            unset.append(f"tier3.{name}")
    return unset


def _known_fields_summary(project: ProjectSchema) -> dict:
    known = {}
    for block_name, block in [("mandatory", project.mandatory), ("tier2", project.tier2), ("tier3", project.tier3)]:
        for field_name, field_value in block:
            if field_value.source != "unset":
                known[f"{block_name}.{field_name}"] = field_value.value
    return known


def _company_history_section(history: Optional[dict]) -> str:
    """Workstream 06: renders this company's own historical project
    range as an extra prompt section, so an LLM estimate is anchored to
    what THIS company has actually built rather than only a generic
    Indian-construction default. Returns "" (no section at all) when
    there's no usable history yet -- a brand-new company with zero
    reference projects should get exactly the same prompt as before this
    workstream, not a section that says "no data" (which would just be
    noise for the model).
    """
    if not history or not history.get("n_reference_projects"):
        return ""

    lines = [
        "\nThis company's own project history (from its Phase 2 uploads -- prefer this "
        "over the generic ranges above wherever it's available, since it reflects what "
        "THIS company actually builds):",
        f"- {history['n_reference_projects']} of this company's own past projects are on file.",
    ]
    if history.get("typology_counts"):
        lines.append(f"- Typology mix: {history['typology_counts']}")
    if history.get("structural_system_type_counts"):
        lines.append(f"- Structural system mix: {history['structural_system_type_counts']}")
    if history.get("gfa_sqm_range"):
        r = history["gfa_sqm_range"]
        lines.append(f"- GFA range across these projects: {r['min']:.0f}-{r['max']:.0f} sqm (avg {r['avg']:.0f}, n={r['n']}).")
    if history.get("steel_reinforcement_ratio_kg_per_sqm"):
        r = history["steel_reinforcement_ratio_kg_per_sqm"]
        lines.append(
            f"- This company's own steel reinforcement ratio has ranged {r['min']:.1f}-{r['max']:.1f} "
            f"kg/sqm (avg {r['avg']:.1f}, from {r['n']} of its own projects) -- prefer this range over "
            f"the generic tier-based bands above when estimating tier3.steel_reinforcement_ratio_kg_per_sqm."
        )
    if history.get("concrete_vol_per_sqm"):
        r = history["concrete_vol_per_sqm"]
        lines.append(
            f"- This company's own concrete volume has ranged {r['min']:.3f}-{r['max']:.3f} m3/sqm "
            f"(avg {r['avg']:.3f}, from {r['n']} of its own projects) -- useful context for how dense "
            f"this company's structures typically are."
        )
    return "\n".join(lines) + "\n"


def _build_prompt(known: dict, unset_field_names: list[str], history: Optional[dict] = None) -> str:
    return f"""You are estimating conceptual-stage building design parameters for an
Indian construction project, to feed an embodied carbon calculator.

Known project details:
{json.dumps(known, indent=2, default=str)}
{_company_history_section(history)}
Typical Indian RCC-framed construction ranges, to guide realistic estimates:
- Steel reinforcement ratio: 50-70 kg/sqm for low-rise (under 5 floors),
  70-100 kg/sqm for mid-rise (5-15 floors), 100-130 kg/sqm for high-rise
  (15+ floors). Stay within these bands unless the known details clearly
  justify otherwise.
- Concrete grade: M20-M25 for low-rise, M25-M35 for mid-rise, M30-M45 for
  high-rise structural columns/slabs. Valid grades are exactly one of:
  M10, M15, M20, M25, M30, M35, M40, M45, M50.
- Cement type: PPC (fly-ash blend) is the most common choice in current
  Indian residential/commercial construction; PSC (GGBS/slag blend) is
  common in coastal or industrial-adjacent regions; OPC (plain Portland,
  no blend) is less common today but still used. Valid values are
  exactly one of: OPC, PSC, PPC.
- finish_spec_level: valid values are exactly one of: economical,
  standard, premium. Do not use any other word (e.g. not "medium" --
  use "standard" instead).
- site_condition: valid values are exactly one of: normal_soil, rocky,
  waterlogged, reclaimed_land. Do not use any other word (e.g. not
  "urban" -- that describes location, not soil/site condition; use
  normal_soil unless the known details indicate otherwise).
- Number of floors for a residential/commercial building of the given GFA:
  estimate a plausible floor count consistent with typical floor plate
  sizes (roughly 500-1500 sqm per floor for this building type), don't
  just guess a round number unrelated to GFA.

Estimate reasonable values for these fields, based on the above guidance
and typical Indian construction practice for a project matching the known
details:
{json.dumps(unset_field_names, indent=2)}

Respond with ONLY a JSON object mapping each field name (exactly as given,
e.g. "tier2.num_floors") to your estimated value. No explanation, no
markdown formatting, just the raw JSON object."""


def _clamp_numeric_estimates(estimates: dict) -> dict:
    clamped = dict(estimates)

    for field, (lo, hi) in NUMERIC_RANGES.items():
        if field in clamped and isinstance(clamped[field], (int, float)):
            value = clamped[field]
            if lo is not None:
                value = max(value, lo)
            if hi is not None:
                value = min(value, hi)
            if value != clamped[field]:
                print(f"[llm_fallback] Clamped {field}: {clamped[field]} -> {value}")
            clamped[field] = value

    grade_field = "tier3.concrete_grade_mix"
    if grade_field in clamped and clamped[grade_field] not in VALID_CONCRETE_GRADES:
        print(f"[llm_fallback] Invalid concrete grade '{clamped[grade_field]}', dropping estimate for this field.")
        del clamped[grade_field]

    return clamped


def _coerce_enum_estimates(estimates: dict) -> dict:
    """Converts raw string values for enum-backed fields into real enum
    members. A value that isn't a valid member at all (checked
    case-insensitively against the enum's actual values) is dropped with
    a printed warning, not silently kept as an invalid string.
    """
    coerced = dict(estimates)

    for field_path, enum_cls in ENUM_FIELD_TYPES.items():
        if field_path not in coerced:
            continue
        raw_value = coerced[field_path]
        if isinstance(raw_value, enum_cls):
            continue  # already a real enum member -- nothing to do

        match = None
        for member in enum_cls:
            if str(member.value).lower() == str(raw_value).lower():
                match = member
                break

        if match is not None:
            coerced[field_path] = match
        else:
            valid_values = [m.value for m in enum_cls]
            print(
                f"[llm_fallback] Invalid value '{raw_value}' for {field_path} "
                f"(expected one of {valid_values}), dropping estimate for this field."
            )
            del coerced[field_path]

    return coerced


def _placeholder_estimates(unset_field_names: list[str]) -> dict:
    defaults = {
        "tier2.typology": Typology.residential,
        "tier2.num_floors": 10,
        "tier2.has_basement": True,
        "tier2.basement_count": 1,
        "tier2.foundation_type": FoundationType.raft,
        "tier2.finish_spec_level": FinishSpecLevel.standard,
        "tier2.parking_type": "basement",
        "tier2.parking_area_sqm": 0.0,
        "tier3.concrete_grade_mix": "M30",
        "tier3.cement_type": CementType.ppc,  # most common blended cement in current Indian construction
        "tier3.steel_reinforcement_ratio_kg_per_sqm": 65.0,
        "tier3.facade_type": "plaster_paint",
        "tier3.glazing_pct": 20.0,
        "tier3.mep_complexity": MepComplexity.standard,
        "tier3.green_cert_target": "none",
        "tier3.site_condition": SiteCondition.normal_soil,
    }
    return {name: defaults[name] for name in unset_field_names if name in defaults}


def _apply_estimates(project: ProjectSchema, estimates: dict) -> ProjectSchema:
    for field_path, value in estimates.items():
        block_name, field_name = field_path.split(".")
        block = getattr(project, block_name)
        if getattr(block, field_name).source != "unset":
            continue
        setattr(
            block,
            field_name,
            FieldValue(value=value, source="llm-estimated", confidence=LLM_ESTIMATED_CONFIDENCE),
        )
    return project


def fill_missing_fields(project: ProjectSchema) -> ProjectSchema:
    unset = _unset_fields(project)
    if not unset:
        return project

    history = company_history.historical_ranges(project.company_id)
    prompt = _build_prompt(_known_fields_summary(project), unset, history=history)
    try:
        estimates = chat_json(prompt)
        estimates = _clamp_numeric_estimates(estimates)
        estimates = _coerce_enum_estimates(estimates)
    except (LLMUnavailableError, Exception) as e:
        print(f"[llm_fallback] LLM call failed ({e}), using placeholder estimates instead.")
        estimates = _placeholder_estimates(unset)

    return _apply_estimates(project, estimates)