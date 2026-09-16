"""The supported way to record a NEW emission factor value for a
category -- Workstream 09. Never hand-edit app/data/ice_db/
emission_factors.json (generated) or factor_history.json's entries
in place (loses the audit trail); this script does both steps
correctly: closes out the previously-current entry's valid_to,
appends the new entry, and regenerates the live snapshot.

USAGE (from backend/):
    python scripts/update_emission_factor.py \\
        --category aluminium \\
        --value '{"ef_kgco2e_per_kg": 27.5, "ef_source": "...", "evidence_tier": "ifc_primary_source"}' \\
        --effective-from 2026-11-01 \\
        --note "Re-sourced from IFC's 2026 update -- see PR #123"

--value takes a JSON object with WHATEVER fields the category's own
payload shape needs (this deliberately isn't a fixed schema across
categories -- see factor_history.json's existing entries for the shape a
given category currently uses, e.g. aluminium's by_product_form
breakdown vs a simpler category with just ef_kgco2e_per_kg/ef_source/
evidence_tier). The new value is NOT merged with the old one -- you are
writing the complete new payload for this category, same as every
existing entry in factor_history.json already is.

Adding a brand-new category (not previously in factor_history.json) also
works -- it just starts that category's history at the given
--effective-from with no prior entry to close out.

Refuses (does not write anything) if --effective-from is not strictly
after the current entry's valid_from -- history entries must be in
chronological order; this is not a way to edit or backdate an existing
entry.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.factor_history import HISTORY_PATH, load_history  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", required=True)
    parser.add_argument("--value", required=True, help="JSON object -- the complete new payload for this category.")
    parser.add_argument("--effective-from", required=True, help="ISO date this value takes effect, e.g. 2026-11-01.")
    parser.add_argument("--note", required=True, help="One-line changelog note -- why this value changed, and citing the new source.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing anything.")
    args = parser.parse_args()

    try:
        new_value = json.loads(args.value)
    except json.JSONDecodeError as e:
        parser.error(f"--value must be valid JSON: {e}")
    if not isinstance(new_value, dict):
        parser.error("--value must be a JSON object.")

    try:
        effective_from = datetime.strptime(args.effective_from, "%Y-%m-%d").date()
    except ValueError:
        parser.error("--effective-from must be an ISO date, e.g. 2026-11-01.")

    history = load_history()
    entries = history["categories"].setdefault(args.category, [])

    current = next((e for e in entries if e["valid_to"] is None), None)
    if current is not None:
        current_from = datetime.strptime(current["valid_from"], "%Y-%m-%d").date()
        if effective_from <= current_from:
            parser.error(
                f"--effective-from ({args.effective_from}) must be strictly after the current entry's "
                f"valid_from ({current['valid_from']}) -- history entries must stay in chronological order. "
                f"This script records a NEW change; it doesn't edit or backdate an existing one."
            )

    print(f"Category: {args.category}")
    if current is None:
        print("  No prior entry -- this will be the first recorded value.")
    else:
        print(f"  Closing out entry valid_from={current['valid_from']} -> valid_to={args.effective_from}")
        print(f"    (was: {json.dumps(current['value'])[:200]})")
    print(f"  New entry: valid_from={args.effective_from}, valid_to=null")
    print(f"    value: {json.dumps(new_value)[:200]}")
    print(f"    note: {args.note}")

    if args.dry_run:
        print("\nDry run -- nothing written. Re-run without --dry-run to apply.")
        return

    if current is not None:
        current["valid_to"] = args.effective_from
    entries.append(
        {
            "valid_from": args.effective_from,
            "valid_to": None,
            "changelog_note": args.note,
            "value": new_value,
        }
    )

    HISTORY_PATH.write_text(json.dumps(history, indent=2) + "\n")
    print(f"\nWrote {HISTORY_PATH}")

    # Regenerate the live snapshot so the change takes effect immediately
    # -- a recorded-but-not-regenerated history entry would be a silent
    # trap (the calculators would still use the OLD number until someone
    # remembered to run the snapshot script separately).
    from app.services.factor_history import generate_snapshot

    snapshot_path = Path(__file__).resolve().parent.parent / "app" / "data" / "ice_db" / "emission_factors.json"
    snapshot_path.write_text(json.dumps(generate_snapshot(), indent=2) + "\n")
    print(f"Regenerated {snapshot_path}")


if __name__ == "__main__":
    main()