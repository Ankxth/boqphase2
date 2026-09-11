"""Lists all known reference projects and whether each is usable for
BOQ matching (has both GFA metadata and a cached extraction).

Usage (from backend/):
    python scripts/list_references.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import reference_store


def main():
    refs = reference_store.list_references()
    if not refs:
        print("No reference projects registered yet.")
        return

    for r in refs:
        status = "USABLE" if r["usable_for_matching"] else "incomplete"
        print(f"[{status}] {r['slug']}")
        print(f"  structural_system_type: {r['structural_system_type']}")
        print(f"  typology: {r['typology']}")
        print(f"  gfa_sqm: {r['gfa_sqm']}")
        print(f"  has_extraction: {r['has_extraction']}")
        print()


if __name__ == "__main__":
    main()