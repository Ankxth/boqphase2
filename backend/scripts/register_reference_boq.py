"""Register a reference BOQ: runs extraction and records/updates its
metadata (GFA, structural system, typology) in one step.

This is the intended way to add a new reference project going forward,
including updating a project once its GFA arrives without needing to
re-run extraction.

Usage (from backend/):
    # Full registration: extract + set metadata
    python scripts/register_reference_boq.py botanico app/data/reference_boqs/Botanico_BOQ.xlsx \\
        --structural-system rcc_frame --typology residential --gfa 45000

    # Once GFA arrives later for an already-extracted project, update
    # just that field without re-running extraction:
    python scripts/register_reference_boq.py botanico --gfa 45000 --metadata-only

    # Deterministic-only extraction (skip the LLM-assisted tier):
    python scripts/register_reference_boq.py botanico app/data/reference_boqs/Botanico_BOQ.xlsx --no-llm

structural_system_type must match one of ProjectSchema's
StructuralSystemType values (rcc_frame, load_bearing_masonry,
steel_frame, composite). typology must match one of Typology's values
(residential, commercial, institutional, mixed_use).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import boq_cache, company_store, reference_store
from app.services.boq_extractor import extract_boq


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("slug", help="Project slug, e.g. 'botanico'")
    parser.add_argument(
        "boq_path", nargs="?", help="Path to the BOQ .xlsx file (omit with --metadata-only)"
    )
    parser.add_argument("--structural-system", default=None)
    parser.add_argument("--typology", default=None)
    parser.add_argument("--gfa", type=float, default=None)
    parser.add_argument("--priced-year", type=int, default=None, help="Year the source BOQ was priced, for inflation adjustment")
    parser.add_argument("--clear-gfa", action="store_true", help="Clear gfa_sqm back to null (e.g. to revert a placeholder test value)")
    parser.add_argument("--no-llm", action="store_true", help="Deterministic extraction only")
    parser.add_argument(
        "--metadata-only", action="store_true", help="Update metadata without re-extracting"
    )
    parser.add_argument(
        "--company", default=company_store.DEFAULT_COMPANY_ID,
        help=f"Company to register this reference project under (Workstream 04). Default: {company_store.DEFAULT_COMPANY_ID!r}",
    )
    args = parser.parse_args()

    if not args.metadata_only and not args.clear_gfa:
        if not args.boq_path:
            print("Error: boq_path is required unless --metadata-only is set")
            sys.exit(1)

        print(f"Extracting {args.boq_path} ...")
        extraction = extract_boq(args.boq_path, use_llm_fallback=not args.no_llm)

        print("\nSheet diagnostics:")
        for sheet, status in extraction["sheet_diagnostics"].items():
            print(f"  {sheet}: {status}")

        print(f"\nResults for '{args.slug}':")
        for category, entry in extraction["materials"].items():
            det = entry.get("deterministic")
            llm = entry.get("llm_assisted")
            if det:
                print(
                    f"  {category}: {det['quantity']:.2f} {det['unit']} "
                    f"(deterministic, {det['line_items']} line items)"
                )
            if llm:
                print(
                    f"  {category}: {llm['quantity']:.2f} {llm['unit']} "
                    f"(llm-assisted, {llm['line_items']} line items)"
                )
        print(f"  unclassified rows: {extraction['unclassified_row_count']}")

        boq_cache.save_extraction(args.slug, extraction, company_id=args.company)
        print(f"\nExtraction saved to cache for '{args.slug}' (company: {args.company})")

    if args.clear_gfa:
        entry = reference_store.clear_gfa(args.slug, company_id=args.company)
        if entry is None:
            print(f"No metadata entry exists yet for '{args.slug}' -- nothing to clear.")
            return
        print(f"\nCleared gfa_sqm for '{args.slug}'. Metadata now: {entry}")
    else:
        entry = reference_store.upsert_metadata(
            args.slug,
            structural_system_type=args.structural_system,
            typology=args.typology,
            gfa_sqm=args.gfa,
            priced_year=args.priced_year,
            company_id=args.company,
        )
        print(f"\nMetadata for '{args.slug}': {entry}")

    ref = reference_store.get_reference(args.slug, company_id=args.company)
    if ref and ref["metadata"].get("gfa_sqm") is not None and ref["extraction"] is not None:
        print(f"'{args.slug}' is now usable for BOQ matching (GFA + extraction both present).")
    else:
        missing = []
        if not ref or ref["metadata"].get("gfa_sqm") is None:
            missing.append("gfa_sqm")
        if not ref or ref["extraction"] is None:
            missing.append("extraction")
        print(f"'{args.slug}' is registered but NOT yet usable for matching -- missing: {', '.join(missing)}")


if __name__ == "__main__":
    main()