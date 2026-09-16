"""Regenerates app/data/ice_db/emission_factors.json from the versioned
source of truth at app/data/ice_db/factor_history.json -- Workstream 09.

WHEN TO RUN THIS:
  - After scripts/update_emission_factor.py records a new value (it calls
    this for you automatically -- you don't normally need to run this
    script directly).
  - If you ever hand-edit factor_history.json directly (not recommended;
    prefer update_emission_factor.py) and need to regenerate the live
    snapshot from it.
  - With --as-of, to reproduce what the snapshot looked like on a past
    date -- e.g. to explain why an old report used a different number
    than today's calculator would give.

WHAT IT IS NOT:
  - Not a place to hand-edit factor values. emission_factors.json is a
    GENERATED file as of this workstream; edit factor_history.json (via
    update_emission_factor.py) instead, or your change will be silently
    overwritten the next time this script runs.

USAGE (from backend/):
    python scripts/generate_emission_factors_snapshot.py               # dry run: diffs against the live file, writes nothing
    python scripts/generate_emission_factors_snapshot.py --write        # writes app/data/ice_db/emission_factors.json
    python scripts/generate_emission_factors_snapshot.py --as-of 2026-09-01 --out /tmp/snapshot_2026-09-01.json
                                                                         # reproduces a past snapshot to a SEPARATE file --
                                                                         # never touches the live emission_factors.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.factor_history import generate_snapshot  # noqa: E402

LIVE_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "ice_db" / "emission_factors.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="Write the regenerated snapshot to the live emission_factors.json (default: dry-run diff only).")
    parser.add_argument("--as-of", default=None, help="Reproduce the snapshot as it stood on this ISO date instead of the current one. Implies --out (never writes the live file).")
    parser.add_argument("--out", default=None, help="Write to this path instead of the live emission_factors.json. Required when --as-of is given.")
    args = parser.parse_args()

    if args.as_of and not args.out:
        parser.error("--as-of requires --out -- a historical snapshot is never written to the live emission_factors.json.")

    new_snapshot = generate_snapshot(as_of=args.as_of)
    new_text = json.dumps(new_snapshot, indent=2, sort_keys=False) + "\n"

    target_path = Path(args.out) if args.out else LIVE_SNAPSHOT_PATH

    if args.as_of:
        target_path.write_text(new_text)
        print(f"Wrote historical snapshot as of {args.as_of} to {target_path}")
        if new_snapshot.get("_missing_as_of_this_date"):
            print(f"  NOTE: no recorded value yet as of that date for: {new_snapshot['_missing_as_of_this_date']}")
        return

    old_text = LIVE_SNAPSHOT_PATH.read_text() if LIVE_SNAPSHOT_PATH.exists() else ""
    if old_text == new_text:
        print("No change -- the live snapshot already matches factor_history.json's current entries.")
        return

    old_snapshot = json.loads(old_text) if old_text else {}
    old_cats = {k for k in old_snapshot if not k.startswith("_")}
    new_cats = {k for k in new_snapshot if not k.startswith("_")}
    changed = sorted(
        cat for cat in old_cats & new_cats
        if old_snapshot.get(cat) != new_snapshot.get(cat)
    )
    added = sorted(new_cats - old_cats)
    removed = sorted(old_cats - new_cats)

    print("Diff against the live emission_factors.json:")
    if changed:
        print(f"  Changed categories: {changed}")
    if added:
        print(f"  New categories: {added}")
    if removed:
        print(f"  Categories no longer in history: {removed}")
    if not (changed or added or removed):
        print("  (Only metadata fields differ -- category payloads are identical.)")

    if args.write:
        target_path.write_text(new_text)
        print(f"Wrote {target_path}")
    else:
        print("Dry run -- nothing written. Re-run with --write to apply.")


if __name__ == "__main__":
    main()