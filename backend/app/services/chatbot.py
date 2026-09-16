"""Workstream 12: Phase 3's "what-if" chatbot -- the last piece the
roadmap's own Phase 3 design sketch named:

    "The chatbot should inherit [substitution.py's] rule exactly -- a
    question like 'what if I use M40 instead of M30' should resolve to
    an actual tool call into the existing recompute path (swap grade,
    re-run calculate_from_boq or the calculation engine, diff the
    result), with the LLM used only to parse the question into that call
    and narrate the answer -- never to invent the carbon or cost delta
    itself. Scoping the chatbot's tool surface tightly (swap category,
    swap grade, swap cement type, swap supplier) keeps this honest and
    keeps the answer auditable."

Two deliberate scope decisions, stated plainly rather than left implicit:

1. Narration is ALWAYS a deterministic template (_narrate below), never
   a second LLM call, even though the roadmap's own wording ("narrate
   the answer") would allow one. A narration call risks the model
   silently rephrasing a number wrong in prose -- a wrong digit reads
   identically to a right one in a sentence, and this project's whole
   substitution discipline (substitution.py, boq_carbon/
   substitution_engine.py, Workstream 05's llm_classifier
   closed-vocabulary rule) exists specifically to keep every number's
   origin traceable to real code, never to the model. Going one step
   stricter than asked costs nothing here -- the template already states
   the real numbers plainly and legibly.

2. The tool surface operates on a project's PHASE 1 record (concrete +
   steel only -- calculate_embodied_carbon()'s own documented scope),
   not an uploaded BOQ/WO's full material mix. This is what makes an
   ongoing "what if" conversation possible at all: Phase 1's
   ProjectSchema is the one pipeline in this codebase with a stable,
   persisted, repeatedly-recomputable representation (see Workstream
   11's phase1_estimate baseline for the same reasoning). A BOQ/WO-scoped
   "swap category" question (e.g. natural stone -> tile, the roadmap's
   other named tool) is NOT covered here -- Phase 3's baseline doesn't
   retain the uploaded file for boq_carbon/substitution_engine.py to
   recompute against, and reinventing that persistence just for chat is
   out of scope for this workstream. That capability already exists,
   unchanged, at POST /boq-carbon/substitute against a fresh upload.
   Every project this chatbot can talk about needs a Phase 1 record --
   automatic for a phase1_estimate-sourced Phase 3 project (Workstream
   11), and one POST /form call away for a boq/wo-sourced one.

Parsing (LLM, with a deterministic fallback): mirrors llm_fallback.py's
own established pattern exactly -- try chat_json() against a
closed-vocabulary prompt (the model may only name one of the four real
tool names below, matching Workstream 05's llm_classifier discipline),
and on ANY failure (no provider configured, network error, malformed
JSON) fall back to a keyword/regex parser that covers the same four
tools without needing a live LLM at all. Both paths are validated
identically afterward -- a keyword-parsed grade and an LLM-parsed grade
go through the exact same _valid_grades() check, so parse_source never
changes how strictly a parameter is trusted.

Execution: every tool reuses the SAME clone-project-and-recompute
pattern substitution.py already established (a deep copy with one field
changed, run through the real calculate_embodied_carbon()), and the
supplier-swap tool reads the same shared app/services/supplier_catalog.py
module Workstream 08 built specifically so "Phase 1, Phase 2, and the
Phase 3 chatbot all read from this one catalog" (the roadmap's own
words). No new carbon math exists anywhere in this file.

Workstream 13 addition: four read-only "query" tools (get_carbon_
breakdown, get_totals, get_benchmark_comparison, get_project_end_
estimate) answering direct questions about a project's carbon/cost that
WS12's swap-only surface had no way to answer at all -- "how much carbon
does steel contribute", "what's my total cost", "how does this compare
to a typical building", "how much will this project have used by the
end". Same discipline as the swap tools: every figure is read straight
off an already-computed CalculationResult/CostEstimate/BenchmarkResult/
DashboardResult, never estimated by the model.

get_project_end_estimate ("by the end of this project") picks the best
available source, in order: (1) a real bills-based projection from
Workstream 10's dashboard, when at least one bill has been recorded;
(2) failing that, this project's recorded Phase 3 baseline total (real
BOQ/WO-derived, or Workstream 11's Phase 1-estimated one -- whichever
was actually recorded); (3) failing that, a live recompute of the
current Phase 1 record. The `source` field on the response says exactly
which was used, so "estimated" and "extrapolated from real bills" are
never presented identically. A per-material split (steel/concrete),
when asked for, is ALWAYS derived from the Phase 1 record's own current
material-mix ratio applied proportionally to whichever total was
selected -- disclosed explicitly in both the data and the narration,
since Phase 3's stored Coverage data (see coverage.py) has no
per-material carbon breakdown of its own to split a BOQ/WO-derived total
by, only aggregate value/coverage percentages.
"""

from __future__ import annotations

import re
from typing import Callable, Literal, Optional

from pydantic import BaseModel

from app.schemas.project_schema import CementType, FieldValue, ProjectSchema
from app.services import phase3, project_store
from app.services.benchmark import compute_benchmark
from app.services.calculation_engine import CalculationResult, MaterialBreakdown, calculate_embodied_carbon
from app.services.cost_estimation import estimate_cost
from app.services.ice_factors import load_factors
from app.services.llm_client import LLMUnavailableError, chat_json
from app.services.supplier_catalog import list_fixed_factor_alternatives_for_category

ToolName = Literal[
    # Workstream 12 -- "what if" (hypothetical swap) tools
    "swap_cement_type", "swap_concrete_grade", "swap_steel_ratio", "swap_steel_supplier",
    # Workstream 13 -- read-only "query" tools (no hypothetical, just report
    # already-computed data)
    "get_carbon_breakdown", "get_totals", "get_benchmark_comparison", "get_project_end_estimate",
]

# The closed tool vocabulary -- both the LLM parser and the keyword
# fallback may only ever name one of these eight. Also served directly by
# GET /phase3/chat/tools so a frontend can show suggested prompts without
# hardcoding this list a second time.
#
# Workstream 13 split the surface into two kinds, both still governed by
# the same rule: the LLM only ever picks a tool and extracts its
# parameters, every number comes from real code. "Swap" tools compute a
# hypothetical (before/after, ChatAnswer's current_value/suggested_value/
# carbon_kg_before/carbon_kg_after fields). "Query" tools report the
# project's current or projected state with no hypothetical involved
# (ChatAnswer's `data` field) -- this is the direct answer to "how much
# carbon does steel contribute" / "what's my total cost" / "how does this
# compare to a typical building" / "how much will this project have used
# by the end", none of which WS12's swap-only surface could answer.
TOOL_CATALOG: dict[str, dict] = {
    "swap_cement_type": {
        "kind": "swap",
        "description": "What if the project used a different cement type?",
        "params": {"target_cement_type": "one of OPC | PSC | PPC"},
        "example_question": "What if I switched to PPC cement?",
    },
    "swap_concrete_grade": {
        "kind": "swap",
        "description": "What if the project used a different concrete grade?",
        "params": {"target_grade": "one of M10 | M15 | M20 | M25 | M30 | M35 | M40 | M45 | M50"},
        "example_question": "What if I use M40 instead of M30?",
    },
    "swap_steel_ratio": {
        "kind": "swap",
        "description": "What if the project used a different steel reinforcement ratio?",
        "params": {"target_ratio_kg_per_sqm": "a positive number"},
        "example_question": "What if steel reinforcement was 60 kg/sqm?",
    },
    "swap_steel_supplier": {
        "kind": "swap",
        "description": "What if the project switched to a lower-carbon, EPD-verified steel supplier from the shared catalog?",
        "params": {},
        "example_question": "What if I used a greener steel supplier?",
    },
    "get_carbon_breakdown": {
        "kind": "query",
        "description": "How much embodied carbon does concrete or steel currently contribute, at this project's present state?",
        "params": {"material": "optional -- one of concrete | steel | all (default all)"},
        "example_question": "How much carbon does steel contribute?",
    },
    "get_totals": {
        "kind": "query",
        "description": "What is this project's current total embodied carbon and estimated cost, including per-sqm figures?",
        "params": {},
        "example_question": "What's my total carbon and cost so far?",
    },
    "get_benchmark_comparison": {
        "kind": "query",
        "description": "How does this project's embodied carbon per sqm compare to a typical building of the same size and structural system?",
        "params": {},
        "example_question": "How does this compare to a typical building?",
    },
    "get_project_end_estimate": {
        "kind": "query",
        "description": (
            "What total (or per-material) embodied carbon is this project projected to reach by "
            "completion -- extrapolated from recorded bills when available, otherwise from this "
            "project's baseline or Phase 1 concept estimate."
        ),
        "params": {"material": "optional -- one of concrete | steel | all (default all)"},
        "example_question": "How much carbon will steel contribute by the end of this project?",
    },
}


class ChatToolCall(BaseModel):
    tool: Optional[ToolName] = None
    params: dict = {}
    parse_source: Literal["llm", "keyword_fallback"]
    # Set only when tool is None -- what kinds of questions ARE answerable,
    # so the caller has something actionable rather than a bare failure.
    clarification: Optional[str] = None


class ChatAnswer(BaseModel):
    project_id: str
    company_id: str
    question: str
    tool_call: ChatToolCall
    applied: bool
    # Populated only for the four Workstream 12 "swap" tools -- kept
    # exactly as shipped so nothing that already reads this response
    # shape breaks.
    current_value: Optional[str] = None
    suggested_value: Optional[str] = None
    carbon_kg_before: Optional[float] = None
    carbon_kg_after: Optional[float] = None
    savings_kg: Optional[float] = None
    savings_pct: Optional[float] = None
    requires_engineering_review: Optional[bool] = None
    # Workstream 13: the structured result for any of the four "query"
    # tools -- shape varies by tool, see each tool's executor and
    # TOOL_CATALOG's description. Always None for a swap tool, which
    # uses the before/after fields above instead.
    data: Optional[dict] = None
    answer_text: str
    error: Optional[str] = None


# --------------------------------------------------------------------------
# Parsing -- LLM first, deterministic keyword fallback on any failure
# --------------------------------------------------------------------------

_GRADE_RE = re.compile(r"\bm\s?-?\s?(10|15|20|25|30|35|40|45|50)\b", re.IGNORECASE)
_CEMENT_RE = re.compile(r"\b(opc|psc|ppc)\b", re.IGNORECASE)
_RATIO_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kg\s*(?:/|per)\s*sq\.?\s*m", re.IGNORECASE)
_SUPPLIER_KEYWORDS = (
    "supplier", "green steel", "greener steel", "recycled steel",
    "low-carbon steel", "low carbon steel", "epd",
)
_VAGUE_STEEL_KEYWORDS = ("steel ratio", "reduce steel", "less steel", "optimi", "reinforcement ratio")

# Workstream 13: query-intent keyword sets. Checked AFTER the swap
# patterns above (so an explicit swap phrasing always wins) and in this
# specific relative order among themselves, because a real question can
# trigger more than one: "how much carbon would steel contribute BY THE
# END of this project" mentions both a material and a breakdown verb
# ("contribute") AND a project-end phrase -- checking project-end first
# is what makes that resolve to get_project_end_estimate(material=
# "steel") rather than the narrower get_carbon_breakdown.
_PROJECT_END_KEYWORDS = (
    "by the end", "by project end", "at completion", "when complete", "when finished",
    "final total", "at the end of", "over the life of", "total by the time",
)
_BENCHMARK_KEYWORDS = ("typical building", "compare", "comparison", "benchmark", "average building")
_BREAKDOWN_KEYWORDS = ("contribute", "breakdown", "how much carbon does", "how much co2", "share of", "responsible for")
_TOTALS_KEYWORDS = (
    "total carbon", "total cost", "total co2", "per sqm", "per sq m", "so far",
    "current carbon", "current cost", "how much carbon", "how much cost", "how much co2",
)

_GENERIC_CLARIFICATION = (
    "I can currently answer what-if questions about switching cement type (OPC/PSC/PPC), "
    "concrete grade (e.g. M30 to M40), the steel reinforcement ratio (kg/sqm), or switching "
    "to a lower-carbon steel supplier from the catalog -- plus direct questions about this "
    "project's current carbon/cost breakdown, its total carbon and cost, how it compares to "
    "a typical building, or its projected carbon by the end of the project."
)


_REJECT_PHRASE_RE = re.compile(r"\b(?:instead of|rather than|as opposed to|over|not)\b", re.IGNORECASE)


def _pick_target(pattern: re.Pattern, question: str) -> Optional[str]:
    """Which of possibly several regex matches is the TARGET (the change
    being asked about) rather than the thing being replaced. Two
    conventions this project's own examples actually use, and they
    disagree about word order:

    - "X instead of Y" / "X rather than Y" -- X, the FIRST mention, is
      the target. This is the roadmap's own worked example verbatim:
      "what if I use M40 instead of M30" means M40 is being proposed,
      M30 is the status quo being replaced.
    - "switch/change from Y to X" -- X, the LAST mention, is the target.

    Disambiguated by checking whether a reject-phrase ("instead of",
    "rather than", ...) sits BETWEEN the first and second match: if so,
    the first mention is the target and the text right after the phrase
    is what's being rejected. Otherwise (an ordinary "from Y to X", or
    no connecting phrase at all) falls back to the LAST mention, the
    most common "closing" position for the thing actually being
    proposed. With only one match, that's the target outright.
    """
    matches = list(pattern.finditer(question))
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0].group(0)

    between = question[matches[0].end() : matches[1].start()]
    if _REJECT_PHRASE_RE.search(between):
        return matches[0].group(0)
    return matches[-1].group(0)


def _parse_with_keywords(question: str) -> ChatToolCall:
    q = question.lower()

    cement_target = _pick_target(_CEMENT_RE, question)
    if cement_target:
        return ChatToolCall(
            tool="swap_cement_type", params={"target_cement_type": cement_target.upper()}, parse_source="keyword_fallback"
        )

    grade_target = _pick_target(_GRADE_RE, question)
    if grade_target:
        grade_num = re.sub(r"[^\d]", "", grade_target)
        return ChatToolCall(
            tool="swap_concrete_grade", params={"target_grade": f"M{grade_num}"}, parse_source="keyword_fallback"
        )

    ratio_match = _RATIO_RE.search(question)
    if ratio_match:
        return ChatToolCall(
            tool="swap_steel_ratio",
            params={"target_ratio_kg_per_sqm": float(ratio_match.group(1))},
            parse_source="keyword_fallback",
        )

    if any(kw in q for kw in _SUPPLIER_KEYWORDS):
        return ChatToolCall(tool="swap_steel_supplier", params={}, parse_source="keyword_fallback")

    if any(kw in q for kw in _VAGUE_STEEL_KEYWORDS):
        return ChatToolCall(
            tool=None, params={}, parse_source="keyword_fallback",
            clarification=(
                "I can tell this is about steel, but not a target ratio -- try a phrasing like "
                "'what if steel reinforcement was 60 kg/sqm?'"
            ),
        )

    # -- Workstream 13: query intents. "material_mentioned" is reused
    # across several branches below, so it's resolved once up front.
    if "steel" in q:
        material_mentioned = "steel"
    elif "concrete" in q:
        material_mentioned = "concrete"
    else:
        material_mentioned = None

    if any(kw in q for kw in _PROJECT_END_KEYWORDS):
        params = {"material": material_mentioned} if material_mentioned else {}
        return ChatToolCall(tool="get_project_end_estimate", params=params, parse_source="keyword_fallback")

    if any(kw in q for kw in _BENCHMARK_KEYWORDS):
        return ChatToolCall(tool="get_benchmark_comparison", params={}, parse_source="keyword_fallback")

    if any(kw in q for kw in _BREAKDOWN_KEYWORDS):
        # A material name narrows it; without one, "breakdown" still
        # means something -- the full concrete/steel split.
        params = {"material": material_mentioned} if material_mentioned else {"material": "all"}
        return ChatToolCall(tool="get_carbon_breakdown", params=params, parse_source="keyword_fallback")

    if any(kw in q for kw in _TOTALS_KEYWORDS):
        return ChatToolCall(tool="get_totals", params={}, parse_source="keyword_fallback")

    if material_mentioned:
        # A material was named but no clear breakdown verb -- still a
        # reasonable breakdown request ("what about steel?").
        return ChatToolCall(tool="get_carbon_breakdown", params={"material": material_mentioned}, parse_source="keyword_fallback")

    return ChatToolCall(tool=None, params={}, parse_source="keyword_fallback", clarification=_GENERIC_CLARIFICATION)


def _build_parse_prompt(question: str) -> str:
    tools_desc = "\n".join(
        f'- "{name}": {spec["description"]} Parameters: {spec["params"]}' for name, spec in TOOL_CATALOG.items()
    )
    return f"""You are parsing a construction project manager's what-if question into ONE tool call.

Available tools -- use EXACTLY one of these names, or null if none apply. Do not invent a tool
name that isn't in this list:
{tools_desc}

Question: "{question}"

Respond with ONLY a JSON object of this exact shape:
{{"tool": "<one of the tool names above, or null>", "params": {{...matching that tool's parameters...}}, "clarification": "<if tool is null, one short sentence saying what kinds of what-if questions ARE answerable; omit or leave empty otherwise>"}}

Do not compute or guess any carbon or cost numbers yourself -- your only job is to identify which
change is being asked about and extract its parameters from the question text."""


def parse_question(question: str) -> ChatToolCall:
    try:
        raw = chat_json(_build_parse_prompt(question))
    except (LLMUnavailableError, Exception) as e:
        print(f"[chatbot] LLM parse call failed ({e}), using keyword-based fallback parsing instead.")
        return _parse_with_keywords(question)

    tool = raw.get("tool")
    if tool not in TOOL_CATALOG:  # closed-vocabulary check -- same discipline as Workstream 05's llm_classifier
        tool = None
    params = raw.get("params")
    if not isinstance(params, dict):
        params = {}
    clarification = raw.get("clarification") or None
    if tool is None and not clarification:
        clarification = _GENERIC_CLARIFICATION

    return ChatToolCall(tool=tool, params=params, parse_source="llm", clarification=clarification)


# --------------------------------------------------------------------------
# Execution -- one function per tool, each a clone-project-and-recompute
# against calculate_embodied_carbon(), exactly like substitution.py's own
# pattern. Raises ValueError on an invalid/unusable parameter -- caught by
# answer_question() below and turned into a plain-language error, never a
# silent wrong number.
# --------------------------------------------------------------------------


def _clone_project(project: ProjectSchema) -> ProjectSchema:
    """Same pattern as substitution.py's own _clone_project -- duplicated
    here rather than imported, since that one is private to its module
    (leading underscore) and this keeps the two modules decoupled."""
    cloned = project.model_copy(deep=True)
    cloned.__dict__["_derived"] = dict(project.__dict__.get("_derived", {}))
    return cloned


def _valid_grades() -> list[str]:
    """Single source of truth for which grades actually mean something
    to the engine -- deliberately NOT hardcoded, since
    get_concrete_grade_scale_factor() silently returns 1.0 (no scaling,
    not an error) for an unrecognized grade rather than raising. Without
    this explicit check, asking about a made-up grade like "M99" would
    silently produce a "no difference" answer instead of a clear error."""
    factors = load_factors()
    return sorted(factors["concrete"]["by_grade"]["cem_i"].keys())


def _current_steel_factor_per_kg(actual_result: CalculationResult) -> Optional[float]:
    for item in actual_result.breakdown:
        if item.material.startswith("Reinforcement steel"):
            return item.factor_used
    return None


def _execute_swap_cement_type(project: ProjectSchema, actual_result: CalculationResult, params: dict) -> dict:
    raw_target = str(params.get("target_cement_type", "")).strip().upper()
    try:
        target = CementType(raw_target)
    except ValueError:
        raise ValueError(f"'{raw_target}' isn't a recognized cement type -- valid options are OPC, PSC, PPC.")

    current_value = project.tier3.cement_type.value
    current_enum = current_value if isinstance(current_value, CementType) else (
        CementType(str(current_value).upper()) if current_value else None
    )
    current_label = current_enum.value if current_enum else "not set"

    before = actual_result.total_carbon_kg
    if current_enum == target:
        after = before  # already on the requested type -- a real, correct "no change" answer, not skipped
    else:
        modified = _clone_project(project)
        modified.tier3.cement_type = FieldValue(value=target, source="user-entered", confidence=1.0)
        after = calculate_embodied_carbon(modified).total_carbon_kg

    savings = before - after
    return {
        "current_value": current_label,
        "suggested_value": target.value,
        "carbon_kg_before": before,
        "carbon_kg_after": after,
        "savings_kg": savings,
        "savings_pct": round(savings / before * 100, 2) if before else 0.0,
        "requires_engineering_review": False,  # cement type substitution within IS-code blends is a spec choice, not a safety question -- matches substitution.py's own cement-swap suggestion
        "applied": True,
    }


def _execute_swap_concrete_grade(project: ProjectSchema, actual_result: CalculationResult, params: dict) -> dict:
    raw_target = str(params.get("target_grade", "")).strip().upper().replace(" ", "").replace("-", "")
    valid = _valid_grades()
    if raw_target not in valid:
        raise ValueError(f"'{raw_target}' isn't a recognized concrete grade -- valid options are {', '.join(valid)}.")

    current_value = project.tier3.concrete_grade_mix.value
    current_label = current_value or "not set"

    before = actual_result.total_carbon_kg
    if current_value and str(current_value).upper() == raw_target:
        after = before
    else:
        modified = _clone_project(project)
        modified.tier3.concrete_grade_mix = FieldValue(value=raw_target, source="user-entered", confidence=1.0)
        after = calculate_embodied_carbon(modified).total_carbon_kg

    savings = before - after
    return {
        "current_value": current_label,
        "suggested_value": raw_target,
        "carbon_kg_before": before,
        "carbon_kg_after": after,
        "savings_kg": savings,
        "savings_pct": round(savings / before * 100, 2) if before else 0.0,
        "requires_engineering_review": False,
        "applied": True,
    }


def _execute_swap_steel_ratio(project: ProjectSchema, actual_result: CalculationResult, params: dict) -> dict:
    raw_target = params.get("target_ratio_kg_per_sqm")
    try:
        target = float(raw_target)
    except (TypeError, ValueError):
        raise ValueError(f"'{raw_target}' isn't a usable steel ratio -- give a positive number of kg/sqm.")
    if target <= 0:
        raise ValueError("Steel reinforcement ratio must be a positive number of kg/sqm.")

    current_value = project.tier3.steel_reinforcement_ratio_kg_per_sqm.value
    current_label = f"{current_value:.1f} kg/sqm" if current_value is not None else "not set"

    modified = _clone_project(project)
    modified.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(value=target, source="user-entered", confidence=1.0)
    after = calculate_embodied_carbon(modified).total_carbon_kg
    before = actual_result.total_carbon_kg
    savings = before - after

    return {
        "current_value": current_label,
        "suggested_value": f"{target:.1f} kg/sqm",
        "carbon_kg_before": before,
        "carbon_kg_after": after,
        "savings_kg": savings,
        "savings_pct": round(savings / before * 100, 2) if before else 0.0,
        # ALWAYS True -- a carbon calculator has no basis to say less steel is structurally
        # safe, exactly substitution.py's own steel-ratio suggestion's reasoning.
        "requires_engineering_review": True,
        "applied": True,
    }


def _execute_swap_steel_supplier(project: ProjectSchema, actual_result: CalculationResult, params: dict) -> dict:
    if project.tier3.steel_reinforcement_ratio_kg_per_sqm.value is None:
        raise ValueError("This project has no steel quantity basis set yet, so there's nothing for a supplier swap to apply to.")

    current_factor = _current_steel_factor_per_kg(actual_result)
    if current_factor is None:
        raise ValueError("Couldn't find the project's current effective steel factor to compare against.")

    alternatives = [
        a
        for a in list_fixed_factor_alternatives_for_category("reinforcement_steel")
        if a.fixed_gwp_kgco2e_per_kg is not None and a.fixed_gwp_kgco2e_per_kg < current_factor
    ]
    requested = params.get("supplier_id") or params.get("supplier")
    if requested:
        alternatives = [
            a for a in alternatives if a.id == requested or (a.supplier or "").lower() == str(requested).lower()
        ]

    if not alternatives:
        raise ValueError(
            "No lower-carbon steel supplier alternative is currently available in the shared catalog "
            "for this project's steel factor."
        )

    best = min(alternatives, key=lambda a: a.fixed_gwp_kgco2e_per_kg)

    modified = _clone_project(project)
    after = calculate_embodied_carbon(
        modified,
        steel_factor_override_kgco2e_per_kg=best.fixed_gwp_kgco2e_per_kg,
        steel_factor_override_label=best.product_name,
    ).total_carbon_kg
    before = actual_result.total_carbon_kg
    savings = before - after

    return {
        "current_value": f"{current_factor:.3f} kgCO2e/kg (IFC India, CEA-adjusted)",
        "suggested_value": f"{best.fixed_gwp_kgco2e_per_kg:.3f} kgCO2e/kg ({best.product_name})",
        "carbon_kg_before": before,
        "carbon_kg_after": after,
        "savings_kg": savings,
        "savings_pct": round(savings / before * 100, 2) if before else 0.0,
        # ALWAYS True -- reinforcement steel is structural by definition, matches Workstream 08's
        # own supplier-steel suggestion in substitution.py.
        "requires_engineering_review": True,
        "applied": True,
    }


def _current_material_breakdown(actual_result: CalculationResult) -> tuple[Optional[MaterialBreakdown], Optional[MaterialBreakdown]]:
    """(concrete_item, steel_item) from actual_result.breakdown -- both
    tools below need this same lookup, so it's factored out rather than
    duplicated."""
    concrete_item = next((b for b in actual_result.breakdown if b.material.startswith("Concrete")), None)
    steel_item = next((b for b in actual_result.breakdown if b.material.startswith("Reinforcement steel")), None)
    return concrete_item, steel_item


def _execute_get_carbon_breakdown(project: ProjectSchema, actual_result: CalculationResult, params: dict) -> dict:
    material = str(params.get("material") or "all").strip().lower()
    if material not in ("concrete", "steel", "all"):
        raise ValueError(f"'{material}' isn't a material I can break down -- ask about 'concrete', 'steel', or 'all'.")

    concrete_item, steel_item = _current_material_breakdown(actual_result)
    total = actual_result.total_carbon_kg

    data: dict = {"material": material, "total_carbon_kg": total, "scope_note": actual_result.scope_note}
    # Only include the figures for what was actually asked -- "how much
    # does steel contribute" shouldn't hand back a concrete number too.
    if concrete_item and material in ("concrete", "all"):
        data["concrete_carbon_kg"] = concrete_item.carbon_kg
        data["concrete_pct_of_total"] = round(concrete_item.carbon_kg / total * 100, 2) if total else None
    if steel_item and material in ("steel", "all"):
        data["steel_carbon_kg"] = steel_item.carbon_kg
        data["steel_pct_of_total"] = round(steel_item.carbon_kg / total * 100, 2) if total else None

    return {"data": data, "applied": True}


def _execute_get_totals(project: ProjectSchema, actual_result: CalculationResult, params: dict) -> dict:
    cost_result = estimate_cost(project, actual_result)
    data = {
        "total_carbon_kg": actual_result.total_carbon_kg,
        "carbon_per_sqm": actual_result.carbon_per_sqm,
        "carbon_per_sqft": actual_result.carbon_per_sqft,
        "total_cost_inr": cost_result.total_cost_inr,
        "cost_per_sqm_inr": cost_result.cost_per_sqm_inr,
        "scope_note": actual_result.scope_note,
    }
    return {"data": data, "applied": True}


def _execute_get_benchmark_comparison(project: ProjectSchema, actual_result: CalculationResult, params: dict) -> dict:
    benchmark_result = compute_benchmark(project, actual_result)
    data = {
        "actual_carbon_per_sqm": benchmark_result.actual_carbon_per_sqm,
        "typical_carbon_per_sqm": benchmark_result.baseline_carbon_per_sqm,
        "pct_difference_from_typical": benchmark_result.pct_difference_from_baseline,
        "comparison_label": benchmark_result.comparison_label,
        "floor_band_used": benchmark_result.floor_band_used,
        "disclaimer": benchmark_result.disclaimer,
    }
    return {"data": data, "applied": True}


def _execute_get_project_end_estimate(project: ProjectSchema, actual_result: CalculationResult, params: dict) -> dict:
    material = str(params.get("material") or "all").strip().lower()
    if material not in ("concrete", "steel", "all"):
        raise ValueError(f"'{material}' isn't a material I can project -- ask about 'concrete', 'steel', or 'all'.")

    # Best available source, in order -- see module docstring for the
    # full reasoning: a real bills-based projection beats a recorded
    # baseline beats a live Phase 1 recompute.
    company_id = project.company_id
    project_id = project.project_id
    projected_total: Optional[float] = None
    source: Optional[str] = None

    baseline = phase3.load_baseline(company_id, project_id)
    if baseline is not None:
        bills = phase3.list_bill_periods(company_id, project_id)
        if bills:
            dashboard = phase3.compute_dashboard(company_id, project_id)
            if dashboard.projected_total_gwp_kg_co2e is not None:
                projected_total = dashboard.projected_total_gwp_kg_co2e
                source = "billed_projection"
        if projected_total is None:
            projected_total = baseline.total_gwp_kg_co2e
            source = f"phase3_baseline_{baseline.source_type}"
    if projected_total is None:
        projected_total = actual_result.total_carbon_kg
        source = "phase1_live_estimate"

    data: dict = {"projected_total_carbon_kg": projected_total, "source": source}

    if material != "all":
        concrete_item, steel_item = _current_material_breakdown(actual_result)
        current_total = actual_result.total_carbon_kg
        target_item = steel_item if material == "steel" else concrete_item
        if target_item is None or not current_total:
            raise ValueError(
                f"No current {material} figure is available on this project's Phase 1 record to project a share from."
            )
        share = target_item.carbon_kg / current_total
        data["material"] = material
        data["material_share_pct"] = round(share * 100, 2)
        data["projected_material_carbon_kg"] = projected_total * share
        # Always disclosed -- the split is proportional to the CURRENT Phase 1 mix,
        # not independently re-derived for a boq/wo-sourced total (see module docstring).
        data["material_split_basis"] = "phase1_concept_estimate"

    return {"data": data, "applied": True}


_EXECUTORS: dict[str, Callable[[ProjectSchema, CalculationResult, dict], dict]] = {
    "swap_cement_type": _execute_swap_cement_type,
    "swap_concrete_grade": _execute_swap_concrete_grade,
    "swap_steel_ratio": _execute_swap_steel_ratio,
    "swap_steel_supplier": _execute_swap_steel_supplier,
    "get_carbon_breakdown": _execute_get_carbon_breakdown,
    "get_totals": _execute_get_totals,
    "get_benchmark_comparison": _execute_get_benchmark_comparison,
    "get_project_end_estimate": _execute_get_project_end_estimate,
}


# --------------------------------------------------------------------------
# Narration -- deterministic template, never a second LLM call (see module
# docstring, scope decision #1). One dispatcher, two families: swap tools
# narrate a before/after; query tools narrate their `data` dict.
# --------------------------------------------------------------------------

_CHANGE_DESCRIPTIONS = {
    "swap_cement_type": "switching cement type from {current} to {suggested}",
    "swap_concrete_grade": "switching concrete grade from {current} to {suggested}",
    "swap_steel_ratio": "changing the steel reinforcement ratio from {current} to {suggested}",
    "swap_steel_supplier": "switching reinforcement steel's source from {current} to {suggested}",
}


def _narrate_swap(tool: str, fields: dict) -> str:
    before = fields["carbon_kg_before"]
    after = fields["carbon_kg_after"]
    savings = fields["savings_kg"]
    pct = fields["savings_pct"]

    change_desc = _CHANGE_DESCRIPTIONS[tool].format(current=fields["current_value"], suggested=fields["suggested_value"])
    change_desc = change_desc[0].upper() + change_desc[1:]

    if abs(savings) < 1e-6:
        sentence = (
            f"{change_desc} makes no difference here -- the project is already effectively at that "
            f"value, so embodied carbon stays at {before:,.0f} kgCO2e."
        )
    elif savings > 0:
        sentence = (
            f"{change_desc} would take embodied carbon from {before:,.0f} kgCO2e to {after:,.0f} kgCO2e "
            f"-- a saving of {savings:,.0f} kgCO2e ({pct:.1f}%)."
        )
    else:
        sentence = (
            f"{change_desc} would actually INCREASE embodied carbon, from {before:,.0f} kgCO2e to "
            f"{after:,.0f} kgCO2e -- {abs(savings):,.0f} kgCO2e ({abs(pct):.1f}%) more, not less."
        )

    if fields.get("requires_engineering_review"):
        sentence += " This change requires engineering review before it's applied for real."

    return sentence


def _narrate_carbon_breakdown(fields: dict) -> str:
    d = fields["data"]
    material = d["material"]
    total = d["total_carbon_kg"]

    if material == "steel":
        if "steel_carbon_kg" not in d:
            return "This project has no steel quantity set yet, so there's no steel figure to report."
        return (
            f"Steel reinforcement currently contributes {d['steel_carbon_kg']:,.0f} kgCO2e "
            f"({d['steel_pct_of_total']:.1f}% of this project's {total:,.0f} kgCO2e total). Scope: {d['scope_note']}"
        )
    if material == "concrete":
        if "concrete_carbon_kg" not in d:
            return "This project has no concrete figure available yet."
        return (
            f"Concrete currently contributes {d['concrete_carbon_kg']:,.0f} kgCO2e "
            f"({d['concrete_pct_of_total']:.1f}% of this project's {total:,.0f} kgCO2e total). Scope: {d['scope_note']}"
        )
    parts = []
    if "concrete_carbon_kg" in d:
        parts.append(f"concrete {d['concrete_carbon_kg']:,.0f} kgCO2e ({d['concrete_pct_of_total']:.1f}%)")
    if "steel_carbon_kg" in d:
        parts.append(f"steel {d['steel_carbon_kg']:,.0f} kgCO2e ({d['steel_pct_of_total']:.1f}%)")
    return f"Of this project's {total:,.0f} kgCO2e total: {', and '.join(parts)}. Scope: {d['scope_note']}"


def _narrate_totals(fields: dict) -> str:
    d = fields["data"]
    return (
        f"This project's current Phase 1 estimate is {d['total_carbon_kg']:,.0f} kgCO2e "
        f"({d['carbon_per_sqm']:.1f} kgCO2e/sqm) at an estimated cost of Rs {d['total_cost_inr']:,.0f} "
        f"(Rs {d['cost_per_sqm_inr']:,.0f}/sqm). Scope: {d['scope_note']}"
    )


def _narrate_benchmark(fields: dict) -> str:
    d = fields["data"]
    pct = abs(d["pct_difference_from_typical"])
    direction = "above" if d["pct_difference_from_typical"] > 0 else "below"
    return (
        f"This project is {d['comparison_label']} for its size and structural system -- "
        f"{d['actual_carbon_per_sqm']:.1f} kgCO2e/sqm vs. a typical {d['typical_carbon_per_sqm']:.1f} kgCO2e/sqm "
        f"({pct:.1f}% {direction} typical). {d['disclaimer']}"
    )


_PROJECTION_SOURCE_LABELS = {
    "billed_projection": "extrapolated from the bills recorded against this project so far",
    "phase1_live_estimate": "Phase 1's current conceptual estimate -- no baseline or bills recorded yet",
}


def _narrate_project_end_estimate(fields: dict) -> str:
    d = fields["data"]
    source = d["source"]
    source_label = _PROJECTION_SOURCE_LABELS.get(
        source, f"this project's recorded baseline ({source.replace('phase3_baseline_', '')}-sourced)"
    )
    total = d["projected_total_carbon_kg"]

    if "material" in d:
        return (
            f"By the end of this project, {d['material']} is estimated to contribute about "
            f"{d['projected_material_carbon_kg']:,.0f} kgCO2e ({d['material_share_pct']:.1f}% of the total), "
            f"out of a projected total of {total:,.0f} kgCO2e -- {source_label}. The {d['material']} share is "
            f"derived from this project's current Phase 1 concept-stage material mix, applied proportionally "
            f"to the projected total, not independently re-derived from a real bill of quantities."
        )
    return f"By the end of this project, embodied carbon is estimated at {total:,.0f} kgCO2e -- {source_label}."


_QUERY_NARRATORS: dict[str, Callable[[dict], str]] = {
    "get_carbon_breakdown": _narrate_carbon_breakdown,
    "get_totals": _narrate_totals,
    "get_benchmark_comparison": _narrate_benchmark,
    "get_project_end_estimate": _narrate_project_end_estimate,
}


def _narrate(tool: str, fields: dict) -> str:
    if tool in _CHANGE_DESCRIPTIONS:
        return _narrate_swap(tool, fields)
    return _QUERY_NARRATORS[tool](fields)


# --------------------------------------------------------------------------
# The chatbot itself
# --------------------------------------------------------------------------


def answer_question(project_id: str, company_id: str, question: str) -> ChatAnswer:
    tool_call = parse_question(question)

    if tool_call.tool is None:
        return ChatAnswer(
            project_id=project_id,
            company_id=company_id,
            question=question,
            tool_call=tool_call,
            applied=False,
            answer_text=tool_call.clarification or _GENERIC_CLARIFICATION,
            error="unparseable_question",
        )

    project = project_store.load_project(project_id, company_id=company_id)
    if project is None:
        return ChatAnswer(
            project_id=project_id,
            company_id=company_id,
            question=question,
            tool_call=tool_call,
            applied=False,
            answer_text=(
                f"Project '{project_id}' has no Phase 1 record yet, so there's nothing for me to "
                f"recompute against -- submit it via POST /form first."
            ),
            error="no_phase1_record",
        )

    if project.mandatory.gfa_sqm.value is None:
        return ChatAnswer(
            project_id=project_id,
            company_id=company_id,
            question=question,
            tool_call=tool_call,
            applied=False,
            answer_text="This project has no GFA set yet, so I can't run any what-if calculation on it.",
            error="no_gfa",
        )

    actual_result = calculate_embodied_carbon(project)

    try:
        fields = _EXECUTORS[tool_call.tool](project, actual_result, tool_call.params)
    except ValueError as e:
        return ChatAnswer(
            project_id=project_id,
            company_id=company_id,
            question=question,
            tool_call=tool_call,
            applied=False,
            answer_text=str(e),
            error="invalid_parameters",
        )

    return ChatAnswer(
        project_id=project_id,
        company_id=company_id,
        question=question,
        tool_call=tool_call,
        answer_text=_narrate(tool_call.tool, fields),
        **fields,
    )