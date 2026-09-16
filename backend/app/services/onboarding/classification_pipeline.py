"""Workstream 05: generalized Steps A-E from
scripts/enhance_master_classification.py, as a pure function over an
in-memory master dict.

Every regex, keyword list, and piece of classification reasoning below
is carried over UNCHANGED from the original, Ecopolitan-tested script --
this workstream generalizes WHERE the data comes from (any company's
in-memory master dict, not a hardcoded
/home/claude/wo_carbon_pipeline/... path) and WHERE the category
templates come from (the shared canonical_categories registry, not
hardcoded Python constants), not HOW a description gets classified. If a
future workstream wants to change the classification logic itself, that
change belongs here (or in a new Step), not by re-forking this pipeline
per company.

Steps (same lettering as the original script; step F -- the WO-specific
impact-ranked triage report -- is NOT part of this module, since impact
ranking depends on which document supplied the amounts and isn't
generalizable to a "master dict" abstraction; see
pipeline.run_onboarding_upload for where that now happens):

  Step A -- admin-prefix scope exclusion
  Step B -- abbreviation-expanded material classification (via the
            canonical_categories registry)
  Step C -- dimension mining (NOS/EA rows with an embedded size)
  Step D -- standard weight-table candidates, flagged not auto-applied
  Step E -- quantifiability tagging on everything still need_review

Only rows whose "contributes" field is currently "need_review" are ever
touched by any step -- a row a previous pass already resolved to "yes"
or "no" is left exactly as it was, same discipline as the original
script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.onboarding import canonical_categories
from app.services.onboarding.abbreviation_dictionary import (
    ADMIN_PREFIXES,
    has_admin_prefix,
    normalize_description,
)
from app.services.onboarding.dimension_miner import mine_dimension_mass

MATERIAL_KW_OVERRIDE = re.compile(
    r"\b(steel|concrete|cement|aluminium|aluminum|glass|timber|wood|brick|block|gi\b|ms\b|stainless|copper|\bcu\b|granite|marble|tile|plaster|paint|gypsum|rcc|pcc|masonry|rebar|reinforcement)\b",
    re.I,
)

GRADE_RE = re.compile(r"\bM(\d{2})\b")
STEEL_KW = re.compile(r"\bMS\b|\bmild\s+steel\b|\bISMB\d*\b|\bISMC\d*\b|\bISLB\d*\b|\bangle\b.{0,15}\bbox\b|\bbox\b.{0,15}\bsection", re.I)
GI_KW = re.compile(r"\bGI\b|\bgalvani[sz]ed\b", re.I)
SS_KW = re.compile(r"\bSS\b|\bstainless\s+steel\b", re.I)
SS_NEARBY = re.compile(r"\bhandrail\b|\brailing\b|\brail\b|\bsink\b|\bfixture\b|\bgrill", re.I)
PAINT_KW = re.compile(r"\bOBD\b|\boil\s+bound\s+distemper\b|\bpaint\b|\bdistemper\b", re.I)
GYPSUM_KW = re.compile(r"\bgypsum\b|\bGYP\b|\bPOP\b|\bplaster\s+of\s+paris\b", re.I)
CONCRETE_KW = re.compile(r"\bPCC\b|\bRCC\b|\bconcrete\b", re.I)

MASS_UNITS = {"KG", "KGS", "MT"}
UNQUANTIFIABLE_UNITS = {"LS", "MON", "DAY", "HR", "HRS", "LOT"}
MEP_CONTEXT_RE = re.compile(r"\bPHE\b|\bplumbing\b|\belectrical\b|\bEle\b|\bHVAC\b|\bDG\b|\bfire\s*fighting\b|\bFFS\b", re.I)

STEEL_SECTION_RE = re.compile(r"\bISMB\s?\d+|\bISMC\s?\d+|\bISLB\s?\d+", re.I)
GI_PIPE_RE = re.compile(r"\bG\.?I\.?\)?\s*\d+\s*mm|\bgalvani[sz]ed\b.*\bpipe\b", re.I)
PVC_PIPE_RE = re.compile(r"\bpn\s?\d+\b.*\bpipe\b|\bpipe\b.*\bpn\s?\d+\b", re.I)


def _is_need_review(row: dict) -> bool:
    return (row.get("contributes") or "").strip().lower() == "need_review"


def _concrete_template(desc: str, categories: dict) -> dict:
    """Returns the concrete template UNMODIFIED (material_category stays
    the bare canonical "concrete") -- an earlier version of this function
    suffixed material_category with the detected grade (e.g. "concrete
    (RCC, PPC, grade M30 ...)"), which broke wo_carbon_engine.py's
    _resolve_ef(), which does an EXACT match against "concrete" and
    otherwise falls through to a KeyError. See canonical_categories.py's
    module docstring for the full story. The grade is genuinely useful
    information, but it belongs in unit_note (documentation only, never
    read by any computation path) -- _resolve_ef already independently
    re-detects the real grade from the row's own `desc` text via
    detect_grade() at EF-resolution time, so this function doesn't need
    to (and must not) encode it into a field that IS read for lookup.
    """
    m = GRADE_RE.search(desc)
    grade = f"M{m.group(1)}" if m else None
    t = dict(categories["concrete"])
    if grade:
        t["unit_note"] = t.get("unit_note", "") + f" (Grade detected in description: {grade}; not used in the factor itself -- see module docstring.)"
    return t


# Ordered (key, matcher(desc, unit) -> bool, template_fn(desc, categories) -> dict)
# -- first match wins, same order as the original script's Step B.
_CATEGORY_RULES = [
    ("concrete", lambda desc, unit: bool(CONCRETE_KW.search(desc)) and unit in ("CUM", "M3", "MT", "KG"),
     lambda desc, categories: _concrete_template(desc, categories)),
    ("structural_steel", lambda desc, unit: bool(STEEL_KW.search(desc)) and unit in MASS_UNITS,
     lambda desc, categories: dict(categories["structural_steel"])),
    ("steel_gi_galvanized", lambda desc, unit: bool(GI_KW.search(desc)) and unit in MASS_UNITS,
     lambda desc, categories: dict(categories["steel_gi_galvanized"])),
    ("steel_stainless", lambda desc, unit: bool(SS_KW.search(desc)) and bool(SS_NEARBY.search(desc)) and unit in MASS_UNITS,
     lambda desc, categories: dict(categories["steel_stainless"])),
    ("paint", lambda desc, unit: bool(PAINT_KW.search(desc)),
     lambda desc, categories: dict(categories["paint"])),
    ("plaster_gypsum", lambda desc, unit: bool(GYPSUM_KW.search(desc)),
     lambda desc, categories: dict(categories["plaster_gypsum"])),
]


@dataclass
class ClassificationPassLog:
    admin_excluded: list[tuple] = field(default_factory=list)
    admin_override_kept: list[tuple] = field(default_factory=list)
    category_reclassified: dict[str, list[tuple]] = field(default_factory=dict)
    dimension_mined: list[tuple] = field(default_factory=list)
    weight_table_candidates_flagged: list[tuple] = field(default_factory=list)

    def to_summary_dict(self) -> dict:
        """JSON-safe counts only -- the raw tuples above (which include
        full description text) are for an in-process caller that wants
        to build a human-readable report; a job's persisted summary only
        needs counts.
        """
        return {
            "admin_excluded": len(self.admin_excluded),
            "admin_override_kept": len(self.admin_override_kept),
            "category_reclassified": {k: len(v) for k, v in self.category_reclassified.items()},
            "dimension_mined": len(self.dimension_mined),
            "weight_table_candidates_flagged": len(self.weight_table_candidates_flagged),
        }


def run_classification_pass(master: dict[str, dict]) -> ClassificationPassLog:
    """Mutates `master` IN PLACE (rows already resolved to yes/no are
    left untouched; only need_review rows are ever written to), and
    returns a log of every change made. Categories come from
    canonical_categories.load_canonical_categories(), loaded once per
    call so every row in this pass sees a consistent snapshot of the
    taxonomy even if it's registered a large one call.
    """
    categories = canonical_categories.load_canonical_categories()
    log = ClassificationPassLog()

    # ---- Step A: admin-prefix scope exclusion ----
    for code, row in master.items():
        if not _is_need_review(row):
            continue
        desc = row.get("desc") or ""
        prefix = has_admin_prefix(desc)
        if prefix is None:
            continue
        if MATERIAL_KW_OVERRIDE.search(desc):
            log.admin_override_kept.append((code, desc, prefix))
            continue
        row["contributes"] = "no"
        row["material_category"] = None
        row["unit_note"] = f"Reclassified 'no' (administrative/soft-cost, prefix {prefix!r}: {ADMIN_PREFIXES[prefix]})"
        log.admin_excluded.append((code, desc, prefix))

    # ---- Step B: abbreviation-expanded material classification ----
    for code, row in master.items():
        if not _is_need_review(row):
            continue
        raw_desc = row.get("desc") or ""
        desc = normalize_description(raw_desc)
        unit = (row.get("unit") or "").strip().upper()

        for key, matcher, template_fn in _CATEGORY_RULES:
            if key not in categories:
                continue  # a company's taxonomy snapshot may not (yet) have every seed key
            if matcher(desc, unit):
                row.update(template_fn(desc, categories))
                log.category_reclassified.setdefault(key, []).append((code, raw_desc, unit))
                break

    # ---- Step C: dimension mining (only rows still need_review) ----
    for code, row in master.items():
        if not _is_need_review(row):
            continue
        raw_desc = row.get("desc") or ""
        unit = (row.get("unit") or "").strip().upper()
        if unit not in ("NOS", "EA"):
            continue
        result = mine_dimension_mass(raw_desc)
        if result.kg_per_unit is None:
            continue
        # material -> ef: reuse steel EF for steel-density matches, concrete EF otherwise.
        # material_category MUST be the bare canonical key here, not a
        # descriptive "(dimension-mined mass)" suffix -- see
        # canonical_categories.py's module docstring: wo_carbon_engine.py's
        # _resolve_ef() does an EXACT string match against "concrete" /
        # "reinforcement_steel" and an exact dict-key lookup otherwise, so
        # any suffix breaks EF resolution entirely (the row would
        # silently never compute). The "dimension-mined" provenance is
        # preserved in unit_note below instead, which is documentation
        # only and never read by any computation path.
        if "steel" in (result.density_or_arealmass_source or "").lower() or result.method == "2d_areal_mass":
            steel = categories.get("structural_steel", canonical_categories.SEED_CATEGORIES["structural_steel"])
            ef, ef_source = steel["ef_kgco2e_per_kg"], steel["ef_source"]
            cat = "structural_steel"
        else:
            concrete = categories.get("concrete", canonical_categories.SEED_CATEGORIES["concrete"])
            ef, ef_source = concrete["ef_kgco2e_per_kg"], concrete["ef_source"]
            cat = "concrete"
        row["contributes"] = "yes"
        row["top5"] = "no"
        row["material_category"] = cat
        row["ef_kgco2e_per_kg"] = ef
        row["ef_source"] = ef_source
        row["cea_adjusted"] = "yes"
        row["evidence_tier"] = "assumed_dimension_density"
        row["kg_per_unit"] = result.kg_per_unit
        row["unit_note"] = f"Dimension-mined ({result.method}): {result.detail}. Source for density/areal-mass: {result.density_or_arealmass_source}"
        log.dimension_mined.append((code, raw_desc, unit, result.kg_per_unit, result.method))

    # ---- Step D: standard weight-table candidates -- flagged, NOT
    # auto-applied. Same MEP-scope caution as the original script: a real
    # match against IS 808/1239/4985 (standard_weight_tables.py) is
    # tagged so the capability is visible and ready, but not applied
    # automatically, since most RMT/NOS pipe-section rows carry an MEP
    # context marker and this project's established scope excludes MEP
    # material -- auto-classifying these to "yes" would silently reverse
    # that scope decision through a back door.
    for code, row in master.items():
        if not _is_need_review(row):
            continue
        raw_desc = row.get("desc") or ""
        unit = (row.get("unit") or "").strip().upper()
        if unit not in ("RMT", "M", "NOS"):
            continue
        matched = None
        if STEEL_SECTION_RE.search(raw_desc):
            matched = "IS 808 steel section (ISMB/ISMC/ISLB) -- standard_weight_tables.steel_section_kg_per_m() covers this designation."
        elif GI_PIPE_RE.search(raw_desc):
            matched = "IS 1239 GI pipe -- standard_weight_tables.gi_pipe_kg_per_m() covers this bore, pending MEP-scope confirmation."
        elif PVC_PIPE_RE.search(raw_desc):
            matched = "IS 4985 uPVC pipe -- standard_weight_tables.upvc_pipe_kg_per_m() covers this size/PN class, pending MEP-scope confirmation."
        if matched is None:
            continue
        is_mep = bool(MEP_CONTEXT_RE.search(raw_desc))
        row["quantifiability_note"] = matched + (" [MEP-context marker found in description -- excluded from this dataset's scope pending explicit MEP-scope confirmation, not computed]" if is_mep else " [no MEP marker found -- flagged for manual confirmation before computing]")
        log.weight_table_candidates_flagged.append((code, raw_desc, unit, is_mep))

    # ---- Step E: quantifiability tagging on everything still need_review ----
    for code, row in master.items():
        if not _is_need_review(row):
            continue
        unit = (row.get("unit") or "").strip().upper()
        if unit in UNQUANTIFIABLE_UNITS:
            row["quantifiability"] = "permanently_unquantifiable"
        elif unit in ("RMT", "NOS", "EA", "M", "KM", "SQM", "FT2", "SET"):
            row["quantifiability"] = "solvable_pending"
        else:
            row["quantifiability"] = "unclassified_material"

    return log