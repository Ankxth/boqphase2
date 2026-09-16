"""Run this once per reference BOQ to populate the extraction cache.

Usage (from backend/):
    python scripts/run_boq_extraction.py botanico app/data/reference_boqs/Botanico_BOQ.xlsx
    python scripts/run_boq_extraction.py botanico app/data/reference_boqs/Botanico_BOQ.xlsx --no-llm
    python scripts/run_boq_extraction.py acme_hq some_boq.xlsx --company acme_builders

--no-llm runs the deterministic (header-detected) pass only -- use this
first to verify extraction accuracy against a known-correct total before
trusting the LLM-assisted layer on top of it.

Workstream 04: --company scopes where the extraction is cached
(app.services.company_store). Defaults to company_store.DEFAULT_COMPANY_ID
("provident"), so the two existing usage examples above still work
unchanged.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import boq_cache, company_store
from app.services.boq_extractor import extract_boq


def main():
    company_id = company_store.DEFAULT_COMPANY_ID
    if "--company" in sys.argv:
        i = sys.argv.index("--company")
        company_id = sys.argv[i + 1]
        del sys.argv[i:i + 2]

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_llm = "--no-llm" not in sys.argv

    if len(args) != 2:
        print("Usage: python scripts/run_boq_extraction.py <project_slug> <path_to_boq.xlsx> [--no-llm] [--company <company_id>]")
        sys.exit(1)

    project_slug, file_path = args

    print(f"Extracting {file_path} ... (LLM fallback: {'on' if use_llm else 'off'})")
    extraction = extract_boq(file_path, use_llm_fallback=use_llm)

    print(f"\nSheet diagnostics:")
    for sheet, status in extraction["sheet_diagnostics"].items():
        print(f"  {sheet}: {status}")

    print(f"\nResults for '{project_slug}':")
    for category, entry in extraction["materials"].items():
        det = entry.get("deterministic")
        llm = entry.get("llm_assisted")
        if det:
            print(f"  {category}: {det['quantity']:.2f} {det['unit']} (deterministic, {det['line_items']} line items)")
        if llm:
            print(f"  {category}: {llm['quantity']:.2f} {llm['unit']} (llm-assisted, {llm['line_items']} line items)")
    print(f"  unclassified rows: {extraction['unclassified_row_count']}")

    saved_path = boq_cache.save_extraction(project_slug, extraction, company_id=company_id)
    print(f"\nSaved to {saved_path}")


if __name__ == "__main__":
    main()