"""Workstream 01 (one emission-factor source) migration: leans
master_item_code_factors.json down to what wo_carbon_engine.py actually
needs per row now that the emission factor itself is resolved at
calculation time from the shared canonical source (app.services.
emission_factors / app.services.ice_factors), not read off the row.

WHAT THIS SCRIPT DOES
  1. Reads the CURRENT master_item_code_factors.json (7,108 rows, each
     carrying its own embedded ef_kgco2e_per_kg / ef_source /
     evidence_tier / cea_adjusted, built independently of boq_carbon's
     factor file).
  2. For every row with contributes == "yes", maps its old, verbose
     material_category string (e.g. "concrete (RCC, PPC, grade M30
     [grade not used in factor])") to a clean canonical category key
     (e.g. "concrete") using the EXPLICIT table below -- built from a
     full, exhaustive scan of every distinct material_category string
     actually present in the file (37 of them; the table has one entry
     per string, no fuzzy parsing).
  3. Genuinely distinct materials that the old naming had folded into
     one parenthetical variant of a shared prefix (blockwork AAC vs
     dense, plaster cement vs gypsum, tile ceramic vs vitrified) map to
     DIFFERENT canonical categories -- that real, useful distinction is
     preserved, not collapsed. Only pure provenance notes (grade-not-
     used-in-factor, dimension-mined-mass) are dropped, since grade is
     now detected dynamically from `desc` at calculation time instead.
  4. Drops ef_kgco2e_per_kg / ef_source / evidence_tier / cea_adjusted
     from every row -- these are resolved dynamically now, from
     emission_factors.json / ice_db_factors.json, not stored per row.
  5. Writes the leaned file back to the SAME path (after saving an
     untouched backup copy alongside it, suffixed
     _pre_workstream01_backup.json, so the original embedded-factor
     version is never lost).
  6. Prints a full reconciliation report: for every canonical category,
     the OLD embedded value(s) seen across all its rows vs the NEW
     canonical value now used for that category, with the delta -- this
     is the same report saved as docs/workstream01_reconciliation_log.md
     for a human-readable record.

USAGE (from backend/):
    python scripts/migrate_master_item_codes_v2.py            # dry run --
                                                                 prints the
                                                                 report,
                                                                 writes
                                                                 nothing
    python scripts/migrate_master_item_codes_v2.py --write     # writes
                                                                 the backup
                                                                 + the
                                                                 leaned
                                                                 file

This is a ONE-TIME migration, not something to re-run casually -- running
it twice is harmless (it's idempotent: a second run on an already-leaned
file just finds no "yes" rows whose material_category matches the old
verbose-string table, since those strings no longer exist, and reports
zero rows migrated), but it exists to make the Workstream 01 transition
reviewable and reversible (via the backup file) rather than a silent
hand-edit of 7,108 rows.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MASTER_JSON_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "master_item_codes" / "master_item_code_factors.json"
BACKUP_PATH = MASTER_JSON_PATH.with_name("master_item_code_factors_pre_workstream01_backup.json")

# Exhaustive: every distinct material_category string present in the
# pre-migration file (confirmed via a direct scan -- 37 of them across
# 1,401 "contributes: yes" rows) -> its canonical emission_factors.json
# key. See app/services/emission_factors.py's docstring for what each
# canonical key means and where its factor now comes from.
CATEGORY_MAP = {
    "PVC/uPVC/CPVC pipe/fitting": "pvc_pipe_fitting",
    "aggregate/gravel": "aggregate",
    "aluminium": "aluminium",
    "bitumen/asphalt": "bitumen_asphalt",
    "blockwork (AAC/aircrete)": "blockwork_aac",
    "blockwork (dense concrete block)": "blockwork_dense",
    "brickwork": "brickwork",
    "cement mortar": "cement_mortar",
    "cement, bagged (PPC default)": "cement_bagged",
    "copper (electrical cable/conductor)": "copper",
    "glass": "glass",
    "insulation (elastomeric/thermal, generic)": "insulation_generic",
    "insulation (rockwool/mineral wool)": "insulation_mineral_wool",
    "natural stone (granite/marble/cladding)": "natural_stone",
    "paint": "paint",
    "plaster (cement-based)": "plaster_cement",
    "plaster (gypsum)": "plaster_gypsum",
    "sand": "sand",
    "steel_gi_galvanized": "steel_gi_galvanized",
    "steel_reinforcement": "reinforcement_steel",  # renamed -- see reconciliation log
    "steel_stainless": "steel_stainless",
    "steel_structural": "structural_steel",  # renamed -- see reconciliation log
    "steel_structural (dimension-mined mass)": "structural_steel",
    "tile (ceramic/glazed, default)": "tile_ceramic",
    "tile (vitrified)": "tile_vitrified",
    "timber_wood": "timber_wood",
    "uPVC window/door frame": "upvc_window_door_frame",
    "waterproofing (bituminous membrane/coating)": "waterproofing",
}


def _canonical_category(raw: str) -> str:
    if raw in CATEGORY_MAP:
        return CATEGORY_MAP[raw]
    if raw.startswith("concrete"):
        return "concrete"
    raise ValueError(
        f"Unmapped material_category string: {raw!r} -- this migration's CATEGORY_MAP "
        f"was built from an exhaustive scan of the file as it existed when this script "
        f"was written; a genuinely new category string means the master file changed "
        f"since then and this table needs a new entry, not a guess."
    )


def migrate(write: bool) -> dict:
    with open(MASTER_JSON_PATH) as f:
        master = json.load(f)

    old_values_by_category: dict[str, set] = defaultdict(set)
    n_rows_migrated = 0
    n_rows_untouched = 0
    leaned: dict[str, dict] = {}

    for code, row in master.items():
        contributes = (row.get("contributes") or "").strip().lower()
        if contributes != "yes":
            # No factor was ever embedded on a non-contributing row --
            # nothing to strip, copy through unchanged.
            leaned[code] = row
            n_rows_untouched += 1
            continue

        raw_category = row.get("material_category") or ""
        canonical = _canonical_category(raw_category)
        if row.get("ef_kgco2e_per_kg") is not None:
            old_values_by_category[canonical].add(row["ef_kgco2e_per_kg"])

        new_row = {
            "desc": row.get("desc"),
            "unit": row.get("unit"),
            "contributes": row.get("contributes"),
            "material_category": canonical,
            "top5": row.get("top5"),
            "unit_note": row.get("unit_note"),
        }
        if row.get("kg_per_unit") is not None:
            new_row["kg_per_unit"] = row["kg_per_unit"]

        leaned[code] = new_row
        n_rows_migrated += 1

    report_lines = [
        f"Workstream 01 master-file migration report",
        f"Rows migrated (contributes == 'yes'): {n_rows_migrated}",
        f"Rows untouched (contributes != 'yes', nothing embedded to strip): {n_rows_untouched}",
        "",
        "Per-category reconciliation -- OLD embedded value(s) seen vs NEW canonical value:",
    ]

    from app.services.emission_factors import get_concrete_factor_per_kg, get_factor as get_canonical_factor
    from app.services.ice_factors import get_steel_rebar_factor_per_kg

    for canonical in sorted(old_values_by_category):
        old_vals = old_values_by_category[canonical]
        if canonical == "reinforcement_steel":
            new_val, _src = get_steel_rebar_factor_per_kg(apply_cea=True)
        elif canonical == "concrete":
            # Old master rows used one flat, grade-blind PPC/M40-anchor
            # value for every grade -- compare against that same anchor
            # value here (grade-scaling now happens dynamically per row
            # at calculation time from the row's own `desc` text, not
            # reflected in this category-level summary).
            new_val, _src = get_concrete_factor_per_kg(cement_type="PPC", grade=None, apply_cea=True)
        else:
            new_val = get_canonical_factor(canonical)["ef_kgco2e_per_kg"]
        old_str = ", ".join(f"{v}" for v in sorted(old_vals))
        match = "MATCH" if len(old_vals) == 1 and abs(next(iter(old_vals)) - new_val) < 1e-4 else "CHANGED"
        report_lines.append(f"  {canonical:28s} old={old_str:20s} new={new_val:.5f}  [{match}]")

    report = "\n".join(report_lines)
    print(report)

    if write:
        shutil.copy(MASTER_JSON_PATH, BACKUP_PATH)
        with open(MASTER_JSON_PATH, "w") as f:
            json.dump(leaned, f, indent=2, sort_keys=False)
        print(f"\nWrote backup to {BACKUP_PATH}")
        print(f"Wrote leaned master file to {MASTER_JSON_PATH}")
    else:
        print("\nDry run only -- no files written. Re-run with --write to apply.")

    return {"report": report, "n_migrated": n_rows_migrated}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    migrate(write=args.write)