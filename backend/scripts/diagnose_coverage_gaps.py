"""Diagnostic companion to test_boq_carbon_pipeline.py: instead of showing
the top computed line items, this shows WHY lines did NOT contribute --
grouped by basis_note reason (e.g. "unclassified", "no quantity", "rcc
line with non-volume unit 'xyz'") with counts, so a coverage gap (lines
classified but not computed, or lines never classified at all) can be
diagnosed from real basis_note text instead of guessed at.

Usage (from backend/):
    python scripts/diagnose_coverage_gaps.py <path_to_boq.xlsx> [sheet_name]
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.boq_carbon.engine import calculate_from_boq
from app.services.boq_carbon.parser import extract_from_first_primary_sheet
from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS


def main():
    boq_path = sys.argv[1]
    sheet_name = sys.argv[2] if len(sys.argv) > 2 else None
    if sheet_name is None:
        sheet_name, _ = extract_from_first_primary_sheet(boq_path, SUPPLEMENTARY_SHEET_PATTERNS)

    result = calculate_from_boq(boq_path, sheet_name)

    print(f"\n{result.source_file}  (sheet: {sheet_name})")
    print(f"total={result.n_lines_total}  classified={result.n_lines_classified}  computed={result.n_lines_computed}")

    unclassified = [li for li in result.line_items if li.category is None]
    classified_not_computed = [li for li in result.line_items if li.category is not None and li.gwp_kg_co2e is None]

    print(f"\n--- Unclassified lines: {len(unclassified)} (never matched a material category) ---")
    print("(not itemized -- expected to be large: MEP, sanitary, waterproofing, misc items out of scope)")

    print(f"\n--- Classified but NOT computed: {len(classified_not_computed)} (this is the interesting gap) ---")
    reason_counts = Counter()
    reason_examples = {}
    for li in classified_not_computed:
        # basis_note for these is a short reason string, e.g. "rcc line with non-volume unit 'nos'"
        reason_counts[li.basis_note] += 1
        reason_examples.setdefault(li.basis_note, li)

    for reason, count in reason_counts.most_common(30):
        ex = reason_examples[reason]
        print(f"\n  [{count:>4}x] {reason}")
        print(f"         category={ex.category}  uom={ex.uom!r}  qty={ex.qty}")
        print(f"         e.g. row {ex.row}: {ex.enriched_description[:140]}")

    # Category-level breakdown of the gap: how many classified-not-computed
    # lines belong to each category, so it's clear which categories are
    # under-represented in the final total.
    print(f"\n--- Classified-not-computed lines, by category ---")
    cat_counts = Counter(li.category for li in classified_not_computed)
    for cat, count in cat_counts.most_common():
        print(f"  {cat:22s} {count}")


if __name__ == "__main__":
    main()
