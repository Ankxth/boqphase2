"""Lists all known reference projects and whether each is usable for
BOQ matching (has both GFA metadata and a cached extraction).

Usage (from backend/):
    python scripts/list_references.py
    python scripts/list_references.py --company acme_builders
    python scripts/list_references.py --all-companies
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import company_store, reference_store


def _print_for_company(company_id: str) -> None:
    refs = reference_store.list_references(company_id=company_id)
    if not refs:
        print(f"No reference projects registered yet for '{company_id}'.")
        return

    for r in refs:
        status = "USABLE" if r["usable_for_matching"] else "incomplete"
        print(f"[{status}] {r['slug']}")
        print(f"  structural_system_type: {r['structural_system_type']}")
        print(f"  typology: {r['typology']}")
        print(f"  gfa_sqm: {r['gfa_sqm']}")
        print(f"  has_extraction: {r['has_extraction']}")
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--company", default=company_store.DEFAULT_COMPANY_ID,
        help=f"Company whose reference projects to list. Default: {company_store.DEFAULT_COMPANY_ID!r}",
    )
    parser.add_argument(
        "--all-companies", action="store_true", help="List every company that has any data on disk"
    )
    args = parser.parse_args()

    if args.all_companies:
        company_ids = company_store.list_company_ids()
        if not company_ids:
            print("No companies registered yet.")
            return
        for company_id in company_ids:
            print(f"=== {company_id} ===")
            _print_for_company(company_id)
    else:
        _print_for_company(args.company)


if __name__ == "__main__":
    main()