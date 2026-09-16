"""Orchestrates the classification-enhancement pipeline requested for this
phase (points 1, 3, 6, 7, 8 from the "triage/abbreviation/dimension/
weight-table/quantifiability" instruction set -- point 2 and point 9 are
explicitly deferred, not touched here):

  Step A -- admin-prefix scope exclusion  (supports point 1's "clean up
            need_review" goal, using signal already visible in the
            description text -- NOT the deferred Material Group/Service
            Category legend from point 2)
  Step B -- abbreviation-expanded material classification (point 3)
  Step C -- dimension mining (point 6)
  Step D -- standard weight-table candidates, flagged not auto-applied
            (point 7 -- see rationale in the step itself)
  Step E -- quantifiability tagging on everything still need_review
            (point 8)
  Step F -- impact-ranked triage report against the real Ecopolitan WO's
            own line items (point 1's explicit deliverable)

Writes:
  master_item_code_factors_enhanced.json   -- the updated master file
  classification_enhancement_report.md     -- full change log + triage report
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from abbreviation_dictionary import (
    ADMIN_PREFIXES,
    has_admin_prefix,
    normalize_description,
)
from dimension_miner import mine_dimension_mass
import standard_weight_tables as swt

BASE_MASTER = "/home/claude/wo_carbon_pipeline/master_item_code_factors_patched.json"
WO_PARSED_ITEMS = "/home/claude/wo_parsed_items.json"
OUT_MASTER = "/home/claude/phase2b/master_item_code_factors_enhanced.json"
OUT_REPORT = "/home/claude/phase2b/classification_enhancement_report.md"

MATERIAL_KW_OVERRIDE = re.compile(
    r"\b(steel|concrete|cement|aluminium|aluminum|glass|timber|wood|brick|block|gi\b|ms\b|stainless|copper|\bcu\b|granite|marble|tile|plaster|paint|gypsum|rcc|pcc|masonry|rebar|reinforcement)\b",
    re.I,
)

# --- Step B category templates, each copied field-for-field from an
# already-correctly-classified row of that category in the master file
# itself (same "prove it against a real row" discipline used by the SDC
# fix) -- with two genuinely NEW categories (steel_stainless) sourced from
# ICE DB v4.1, the only project data file with a stainless-steel figure.

CONCRETE_TEMPLATE = {
    "contributes": "yes", "top5": "yes", "ef_kgco2e_per_kg": 0.08386,
    "ef_source": "IFC India Construction Materials Database (2017), Table 14, by cement type, CEA grid-adjusted.",
    "cea_adjusted": "yes", "evidence_tier": "ifc_primary_source",
    "unit_note": "Convert Cum to kg using concrete density 2400 kg/m3 (IFC default), then apply per-kg factor.",
}
STEEL_STRUCTURAL_TEMPLATE = {
    "contributes": "yes", "top5": "yes", "ef_kgco2e_per_kg": 2.34713,
    "ef_source": "IFC India Construction Materials Database (2017), Table 14, p.69 -- 'Steel section', CEA grid-adjusted.",
    "cea_adjusted": "yes", "evidence_tier": "ifc_primary_source",
    "material_category": "steel_structural",
    "unit_note": "Direct mass conversion: qty already in mass units (KG/KGS/MT), apply per-kg factor.",
}
STEEL_GI_TEMPLATE = {
    "contributes": "yes", "top5": "yes", "ef_kgco2e_per_kg": 2.80449,
    "ef_source": "IFC India Construction Materials Database (2017), Table 14 -- Electrogalvanized steel sheet, CEA grid-adjusted.",
    "cea_adjusted": "yes", "evidence_tier": "ifc_primary_source",
    "material_category": "steel_gi_galvanized",
    "unit_note": "Direct mass conversion: qty already in mass units (KG/KGS/MT), apply per-kg factor.",
}
STEEL_STAINLESS_TEMPLATE = {
    "contributes": "yes", "top5": "no", "ef_kgco2e_per_kg": 4.17786,
    "ef_source": "ICE Database v4.1 (Oct 2025), Steel material profile, row 'Steel, Stainless' -- average of 28 datapoints. No IFC India stainless-steel line exists; this is the only project data file with a stainless-steel figure.",
    "cea_adjusted": "no", "evidence_tier": "ice_uk_proxy",
    "material_category": "steel_stainless",
    "unit_note": "Direct mass conversion: qty already in mass units (KG/KGS/MT), apply per-kg factor.",
}
PAINT_TEMPLATE = {
    "contributes": "yes", "top5": "no", "ef_kgco2e_per_kg": 2.6,
    "ef_source": "Retained from the uploaded Embodied Carbon Contributor Flags sheet (ICE Database, Circular Ecology/Univ. of Bath) -- no defensible IFC India match found. (ICE paint, general, midpoint of water/solvent-based range).",
    "cea_adjusted": "no", "evidence_tier": "ice_uk_proxy",
    "material_category": "paint",
    "unit_note": "NEEDS AREAL-MASS ASSUMPTION -- an area-priced row needs a kg/m2 conversion figure; only aluminium (12 kg/m2) and glass (15 kg/m2) have a documented assumption so far. Paint's own areal-mass figure is still open (out of scope for this pass -- see point 9's deferred scope).",
}
GYPSUM_TEMPLATE = {
    "contributes": "yes", "top5": "no", "ef_kgco2e_per_kg": 0.099,
    "ef_source": "IFC India Construction Materials Database (2017), Table 14 -- Gypsum plaster. Raw value, NOT CEA-adjusted.",
    "cea_adjusted": "no", "evidence_tier": "ifc_primary_source",
    "material_category": "plaster (gypsum)",
    "unit_note": "NEEDS AREAL-MASS ASSUMPTION -- an area-priced row needs a kg/m2 conversion figure; only aluminium and glass have one so far.",
}

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


def concrete_grade_template(desc: str) -> dict:
    m = GRADE_RE.search(desc)
    grade = f"M{m.group(1)}" if m else "M10"  # 1:3:6 nominal mix corresponds to M10 per IS 456 nominal-mix table; used as fallback default
    t = dict(CONCRETE_TEMPLATE)
    t["material_category"] = f"concrete (RCC, PPC, grade {grade} [grade not used in factor])"
    return t


def main():
    master = json.load(open(BASE_MASTER))
    wo_items = json.load(open(WO_PARSED_ITEMS))

    log = {
        "admin_excluded": [], "admin_override_kept": [],
        "concrete_reclassified": [], "steel_reclassified": [], "gi_reclassified": [],
        "ss_reclassified": [], "paint_reclassified": [], "gypsum_reclassified": [],
        "dimension_mined": [], "weight_table_candidates_flagged": [],
    }

    # ---- Step A: admin-prefix scope exclusion ----
    for code, row in master.items():
        if (row.get("contributes") or "").strip().lower() != "need_review":
            continue
        desc = row.get("desc") or ""
        prefix = has_admin_prefix(desc)
        if prefix is None:
            continue
        if MATERIAL_KW_OVERRIDE.search(desc):
            log["admin_override_kept"].append((code, desc, prefix))
            continue
        row["contributes"] = "no"
        row["material_category"] = None
        row["unit_note"] = f"Reclassified 'no' (administrative/soft-cost, prefix {prefix!r}: {ADMIN_PREFIXES[prefix]})"
        log["admin_excluded"].append((code, desc, prefix))

    # ---- Step B: abbreviation-expanded material classification ----
    for code, row in master.items():
        if (row.get("contributes") or "").strip().lower() != "need_review":
            continue
        raw_desc = row.get("desc") or ""
        desc = normalize_description(raw_desc)
        unit = (row.get("unit") or "").strip().upper()

        if CONCRETE_KW.search(desc) and unit in ("CUM", "M3", "MT", "KG"):
            row.update(concrete_grade_template(desc))
            log["concrete_reclassified"].append((code, raw_desc, unit))
            continue

        if STEEL_KW.search(desc) and unit in MASS_UNITS:
            row.update(STEEL_STRUCTURAL_TEMPLATE)
            log["steel_reclassified"].append((code, raw_desc, unit))
            continue

        if GI_KW.search(desc) and unit in MASS_UNITS:
            row.update(STEEL_GI_TEMPLATE)
            log["gi_reclassified"].append((code, raw_desc, unit))
            continue

        if SS_KW.search(desc) and SS_NEARBY.search(desc) and unit in MASS_UNITS:
            row.update(STEEL_STAINLESS_TEMPLATE)
            log["ss_reclassified"].append((code, raw_desc, unit))
            continue

        if PAINT_KW.search(desc):
            row.update(PAINT_TEMPLATE)
            log["paint_reclassified"].append((code, raw_desc, unit))
            continue

        if GYPSUM_KW.search(desc):
            row.update(GYPSUM_TEMPLATE)
            log["gypsum_reclassified"].append((code, raw_desc, unit))
            continue

    # ---- Step C: dimension mining (only rows still need_review) ----
    for code, row in master.items():
        if (row.get("contributes") or "").strip().lower() != "need_review":
            continue
        raw_desc = row.get("desc") or ""
        unit = (row.get("unit") or "").strip().upper()
        if unit not in ("NOS", "EA"):
            continue
        result = mine_dimension_mass(raw_desc)
        if result.kg_per_unit is None:
            continue
        # material -> ef: reuse steel EF for steel-density matches, concrete EF otherwise
        if "steel" in (result.density_or_arealmass_source or "").lower() or result.method == "2d_areal_mass":
            ef, ef_source, evidence_tier = STEEL_STRUCTURAL_TEMPLATE["ef_kgco2e_per_kg"], STEEL_STRUCTURAL_TEMPLATE["ef_source"], "ifc_primary_source"
            cat = "steel_structural (dimension-mined mass)"
        else:
            ef, ef_source, evidence_tier = CONCRETE_TEMPLATE["ef_kgco2e_per_kg"], CONCRETE_TEMPLATE["ef_source"], "ifc_primary_source"
            cat = "concrete (dimension-mined mass)"
        row["contributes"] = "yes"
        row["top5"] = "no"
        row["material_category"] = cat
        row["ef_kgco2e_per_kg"] = ef
        row["ef_source"] = ef_source
        row["cea_adjusted"] = "yes"
        row["evidence_tier"] = "assumed_dimension_density"
        row["kg_per_unit"] = result.kg_per_unit
        row["unit_note"] = f"Dimension-mined ({result.method}): {result.detail}. Source for density/areal-mass: {result.density_or_arealmass_source}"
        log["dimension_mined"].append((code, raw_desc, unit, result.kg_per_unit, result.method))

    # ---- Step D: standard weight-table candidates -- flagged, NOT
    # auto-applied. Real IS 808/1239/4985 figures exist (standard_weight_
    # tables.py) but nearly every RMT/NOS pipe-section row actually found
    # in this WO's need_review bucket carries an MEP context marker (Ext/
    # Int PHE, Plumbing, Electrical/Ele, DG, HVAC) -- this project's
    # established scope excludes MEP material. Auto-classifying these to
    # "yes" would silently reverse that scope decision through a back
    # door. Instead: tag them so the weight-table capability is visible
    # and ready to apply the moment MEP scope is confirmed (point 2,
    # deferred) -- they stay need_review with an explicit reason.
    STEEL_SECTION_RE = re.compile(r"\bISMB\s?\d+|\bISMC\s?\d+|\bISLB\s?\d+", re.I)
    GI_PIPE_RE = re.compile(r"\bG\.?I\.?\)?\s*\d+\s*mm|\bgalvani[sz]ed\b.*\bpipe\b", re.I)
    PVC_PIPE_RE = re.compile(r"\bpn\s?\d+\b.*\bpipe\b|\bpipe\b.*\bpn\s?\d+\b", re.I)
    for code, row in master.items():
        if (row.get("contributes") or "").strip().lower() != "need_review":
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
        row["quantifiability_note"] = matched + (" [MEP-context marker found in description -- excluded from this WO's scope pending point-2 legend confirmation, not computed]" if is_mep else " [no MEP marker found -- flagged for manual confirmation before computing]")
        log["weight_table_candidates_flagged"].append((code, raw_desc, unit, is_mep))

    # ---- Step E: quantifiability tagging on everything still need_review ----
    for code, row in master.items():
        if (row.get("contributes") or "").strip().lower() != "need_review":
            continue
        unit = (row.get("unit") or "").strip().upper()
        if unit in UNQUANTIFIABLE_UNITS:
            row["quantifiability"] = "permanently_unquantifiable"
        elif unit in ("RMT", "NOS", "EA", "M", "KM", "SQM", "FT2", "SET"):
            row["quantifiability"] = "solvable_pending"
        else:
            row["quantifiability"] = "unclassified_material"

    Path(OUT_MASTER).write_text(json.dumps(master))

    # ---- Step F: impact-ranked triage (point 1) ----
    amt_by_code = defaultdict(float)
    for it in wo_items.get("items", wo_items if isinstance(wo_items, list) else []):
        amt_by_code[it["code"]] += it["amount"]

    still_nr = {k: v for k, v in master.items() if (v.get("contributes") or "").strip().lower() == "need_review"}
    ranked = sorted(((amt_by_code.get(k, 0.0), k, v) for k, v in still_nr.items() if amt_by_code.get(k, 0.0) > 0), key=lambda x: -x[0])

    write_report(master, log, ranked, amt_by_code)
    print_summary(master, log, ranked)


def print_summary(master, log, ranked):
    from collections import Counter
    print(Counter(v.get("contributes") for v in master.values()))
    print("admin_excluded:", len(log["admin_excluded"]), "| admin_override_kept:", len(log["admin_override_kept"]))
    print("concrete:", len(log["concrete_reclassified"]), "steel:", len(log["steel_reclassified"]),
          "gi:", len(log["gi_reclassified"]), "ss:", len(log["ss_reclassified"]),
          "paint:", len(log["paint_reclassified"]), "gypsum:", len(log["gypsum_reclassified"]))
    print("dimension_mined:", len(log["dimension_mined"]))
    print("weight_table_flagged:", len(log["weight_table_candidates_flagged"]))
    print("still need_review AND present in this WO:", len(ranked), "total Rs:", sum(r[0] for r in ranked))


def write_report(master, log, ranked, amt_by_code):
    lines = ["# Classification enhancement report\n"]
    from collections import Counter
    lines.append("## Final contributes-to-carbon distribution\n")
    for k, v in Counter(row.get("contributes") for row in master.values()).most_common():
        lines.append(f"- {k}: {v}")
    lines.append("\n## Step A -- admin-prefix scope exclusion\n")
    lines.append(f"{len(log['admin_excluded'])} rows reclassified to 'no' (administrative/soft-cost prefixes). {len(log['admin_override_kept'])} rows kept in need_review despite matching a prefix, because they also contain a material keyword (not guessed):\n")
    for code, desc, prefix in log["admin_override_kept"]:
        lines.append(f"  - {code} [{prefix}] {desc!r}")
    lines.append("\n## Step B -- abbreviation-expanded material classification\n")
    for label, key in [("Concrete (PCC/RCC punctuation fix)", "concrete_reclassified"), ("Steel (MS/ISMB/ISMC/ISLB)", "steel_reclassified"),
                        ("GI galvanized", "gi_reclassified"), ("Stainless steel", "ss_reclassified"),
                        ("Paint (OBD)", "paint_reclassified"), ("Gypsum plaster", "gypsum_reclassified")]:
        rows = log[key]
        lines.append(f"\n### {label}: {len(rows)} rows\n")
        for code, desc, unit in rows[:30]:
            lines.append(f"  - {code} [{unit}] {desc!r}")
    lines.append(f"\n## Step C -- dimension mining: {len(log['dimension_mined'])} rows\n")
    for code, desc, unit, kg, method in log["dimension_mined"]:
        lines.append(f"  - {code} [{unit}] {desc!r} -> {kg} kg ({method})")
    lines.append(f"\n## Step D -- standard weight-table candidates flagged (NOT auto-applied): {len(log['weight_table_candidates_flagged'])} rows\n")
    mep_n = sum(1 for r in log["weight_table_candidates_flagged"] if r[3])
    lines.append(f"{mep_n} of these carry an MEP-context marker; {len(log['weight_table_candidates_flagged']) - mep_n} do not (flagged for manual confirmation).\n")
    for code, desc, unit, is_mep in log["weight_table_candidates_flagged"][:40]:
        lines.append(f"  - {code} [{unit}] {desc!r} {'[MEP]' if is_mep else '[non-MEP, needs confirmation]'}")
    lines.append(f"\n## Step F -- impact-ranked need_review (real Ecopolitan WO amounts), top 50 of {len(ranked)}\n")
    lines.append(f"Total Rs still in need_review across this WO: Rs {sum(r[0] for r in ranked):,.0f}\n")
    for amt, code, row in ranked[:50]:
        lines.append(f"  - Rs {amt:>14,.0f}  {code}  [{row.get('unit')}]  {row.get('desc')!r}  (quantifiability={row.get('quantifiability')})")
    Path(OUT_REPORT).write_text("\n".join(lines))


if __name__ == "__main__":
    main()
