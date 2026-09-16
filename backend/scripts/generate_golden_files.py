"""Writes (or previews changes to) the golden-file regression baselines
under tests/golden/ -- Workstream 00 of the Foundation Plan.

WHEN TO RUN THIS:
  - Once, to create the initial baselines (already done -- the four
    golden files are committed).
  - Again, ONLY when a change to the pipeline is intentional and you want
    the regression tests to accept the new numbers as correct going
    forward (e.g. after Workstream 01 unifies the emission factor source
    and a category's value deliberately changes).

WHAT IT IS NOT:
  - Not something to run reflexively when a test fails. A failing golden
    test means the pipeline's output changed -- the first question is
    always "was that change intended?", and the answer decides whether
    you fix the code (regression) or update the golden file (intentional
    change). Regenerating without reading the diff first defeats the
    entire point of this workstream.

USAGE (from backend/):
    python scripts/generate_golden_files.py              # dry run: prints
                                                           # a diff against
                                                           # the existing
                                                           # golden files,
                                                           # writes nothing
    python scripts/generate_golden_files.py --write       # applies the
                                                           # diff, updates
                                                           # tests/golden/*.json
    python scripts/generate_golden_files.py --write --note "reason for the change"
                                                           # records WHY in
                                                           # the golden
                                                           # file's own
                                                           # _meta.changelog

Documents covered, and why one of the four is different from the others:
  - Ecopolitan_BOQ.xlsx / Botanico_BOQ.xlsx (boq_carbon pipeline) and
    Provident Ecopolitan_WO_KPIL.pdf (wo_carbon pipeline) are run for
    real, right here, against the current code -- their golden files are
    always a live, independently-reproduced snapshot.
  - The Botanico Work Order PDF is NOT present in this environment (only
    its printed console output was shared, in an earlier chat message).
    Its golden file is seeded from that pasted output, with
    _meta.verified_by = "user_terminal_output" instead of
    "claude_sandbox_run" -- an honest label, not a silent gap. The moment
    the real PDF is placed at app/data/work_orders/Provident
    Botanico_WO_SICL.pdf, running this script will independently
    reproduce (or correct) those numbers and flip that label for you.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import company_store  # noqa: E402
from tests.golden_utils import GOLDEN_DIR, diff_result, load_golden  # noqa: E402

# Workstream 04 moved this from a single global file to per-company
# storage -- these golden-file regenerations still only ever exercise
# Provident's own data.
MASTER_JSON_PATH = str(company_store.master_item_codes_path(company_store.DEFAULT_COMPANY_ID))

BOQ_SCALAR_FIELDS = ["n_lines_total", "n_lines_classified", "n_lines_computed", "total_gwp_kg_co2e", "total_gwp_tonnes_co2e", "gwp_per_sqm"]
WO_SCALAR_FIELDS = ["n_line_items_parsed", "n_line_items_computed", "total_gwp_kg_co2e", "total_gwp_tonnes_co2e", "gwp_per_sqm", "parse_checksum_ok"]


def _run_boq(source_path: str, floor_area_sqm: float) -> dict:
    from app.services.boq_carbon.engine import calculate_from_boq
    from app.services.boq_carbon.parser import extract_from_first_primary_sheet
    from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS

    sheet, _ = extract_from_first_primary_sheet(source_path, SUPPLEMENTARY_SHEET_PATTERNS)
    r = calculate_from_boq(source_path, sheet, floor_area_sqm=floor_area_sqm, floor_area_basis="built_up_total")
    return {
        "n_lines_total": r.n_lines_total,
        "n_lines_classified": r.n_lines_classified,
        "n_lines_computed": r.n_lines_computed,
        "total_gwp_kg_co2e": r.total_gwp_kg_co2e,
        "total_gwp_tonnes_co2e": r.total_gwp_tonnes_co2e,
        "gwp_per_sqm": r.gwp_per_sqm,
        "by_category": [
            {"category": c.category, "gwp_kg_co2e": c.gwp_kg_co2e, "line_item_count": c.line_item_count}
            for c in r.by_category
        ],
        "_sheet_used": sheet,
    }


def _run_wo(pdf_path: str, master_json_path: str, floor_area_sqm: float) -> dict:
    from app.services.wo_carbon.wo_carbon_engine import calculate_from_work_order

    r = calculate_from_work_order(pdf_path, master_json_path, floor_area_sqm=floor_area_sqm, floor_area_basis="built_up_total")
    return {
        "n_line_items_parsed": r.n_line_items_parsed,
        "n_line_items_computed": r.n_line_items_computed,
        "total_gwp_kg_co2e": r.total_gwp_kg_co2e,
        "total_gwp_tonnes_co2e": r.total_gwp_tonnes_co2e,
        "gwp_per_sqm": r.gwp_per_sqm,
        "parse_checksum_ok": r.parse_checksum_ok,
        "by_category": [
            {"category": c.category, "gwp_kg_co2e": c.gwp_kg_co2e, "line_item_count": c.line_item_count}
            for c in r.by_category
        ],
    }


# Each entry: golden file name -> (source path, run function + args, pipeline label, scalar fields)
DOCUMENTS = {
    "ecopolitan_boq": {
        "pipeline": "boq_carbon",
        "source_path": "app/data/reference_boqs/Ecopolitan_BOQ.xlsx",
        "run": lambda: _run_boq("app/data/reference_boqs/Ecopolitan_BOQ.xlsx", 205981.65),
        "scalar_fields": BOQ_SCALAR_FIELDS,
    },
    "botanico_boq": {
        "pipeline": "boq_carbon",
        "source_path": "app/data/reference_boqs/Botanico_BOQ.xlsx",
        "run": lambda: _run_boq("app/data/reference_boqs/Botanico_BOQ.xlsx", 166022.98),
        "scalar_fields": BOQ_SCALAR_FIELDS,
    },
    "ecopolitan_wo": {
        "pipeline": "wo_carbon",
        "source_path": "app/data/work_orders/Provident Ecopolitan_WO_KPIL.pdf",
        "run": lambda: _run_wo(
            "app/data/work_orders/Provident Ecopolitan_WO_KPIL.pdf",
            MASTER_JSON_PATH,
            205981.65,
        ),
        "scalar_fields": WO_SCALAR_FIELDS,
    },
    "botanico_wo": {
        "pipeline": "wo_carbon",
        "source_path": "app/data/work_orders/Provident Botanico_WO_SICL.pdf",
        "run": lambda: _run_wo(
            "app/data/work_orders/Provident Botanico_WO_SICL.pdf",
            MASTER_JSON_PATH,
            166022.98,
        ),
        "scalar_fields": WO_SCALAR_FIELDS,
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Apply the diff and update tests/golden/*.json (default: dry run, print diff only)")
    ap.add_argument("--note", default=None, help="One-line reason for the change, recorded in the golden file's _meta.changelog. Required with --write if the golden file already existed and differs.")
    ap.add_argument("--only", default=None, help="Comma-separated subset of document names to run (default: all)")
    args = ap.parse_args()

    names = args.only.split(",") if args.only else list(DOCUMENTS.keys())
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    any_diff = False

    for name in names:
        cfg = DOCUMENTS[name]
        print(f"=== {name} ({cfg['pipeline']}) ===")

        if not Path(cfg["source_path"]).exists():
            print(f"  SKIPPED -- source document not found at {cfg['source_path']!r} in this environment.")
            print(f"  (This is expected for botanico_wo until the real PDF is supplied -- see this script's docstring.)")
            print()
            continue

        current = cfg["run"]()
        current["_meta"] = {
            "pipeline": cfg["pipeline"],
            "source_path": cfg["source_path"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "verified_by": "claude_sandbox_run",
        }

        golden_path = GOLDEN_DIR / f"{name}.json"
        if golden_path.exists():
            golden = load_golden(name)
            diffs = diff_result(golden, current, cfg["scalar_fields"])
            if diffs:
                any_diff = True
                print(f"  DIFFERS from committed golden file ({len(diffs)} change(s)):")
                for d in diffs:
                    print(f"    - {d}")
            else:
                print("  No change from committed golden file.")
        else:
            any_diff = True
            print("  No existing golden file -- this will be a NEW baseline.")
            diffs = ["(new golden file)"]

        if args.write:
            if diffs and golden_path.exists() and not args.note:
                print("  Refusing to write: golden file changed but no --note given. Re-run with --note \"why this changed\".")
                sys.exit(1)
            if diffs:
                current["_meta"]["changelog"] = args.note or "initial baseline"
            elif golden_path.exists():
                current["_meta"]["changelog"] = golden["_meta"].get("changelog")
            with open(golden_path, "w") as f:
                json.dump(current, f, indent=2, sort_keys=False)
            print(f"  Wrote {golden_path}")
        print()

    if not args.write and any_diff:
        print("Dry run only -- no files written. Re-run with --write (and --note if updating an existing baseline) to apply.")


if __name__ == "__main__":
    main()