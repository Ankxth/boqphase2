"""Workstream 04 migration: moves this project's existing (single-
company, Provident) data into the new per-company storage layout under
data/companies/<company_id>/ -- see app/services/company_store.py's
docstring for the full layout and rationale.

WHAT THIS SCRIPT MOVES (all of it, into data/companies/provident/):
  1. app/data/master_item_codes/master_item_code_factors.json
     -> data/companies/provident/master_item_codes.json
     (and its _pre_workstream01_backup.json sibling, same new folder,
     same filename -- kept as a sibling, not renamed, since scripts and
     docs already refer to it by that exact name)
  2. app/data/reference_boqs/reference_stats.json
     -> data/companies/provident/reference_projects/reference_stats.json
  3. app/data/reference_boqs/cache/*.json
     -> data/companies/provident/reference_projects/cache/*.json
  4. app/data/projects/*.json
     -> app/data/companies/provident/projects/*.json
     (each file also gets an explicit "company_id": "provident" key
     injected if it doesn't already have one -- not strictly required,
     since ProjectSchema.company_id defaults to "provident" and would
     fill this in on load anyway, but explicit is better than relying on
     a caller remembering that default forever)

WHAT THIS SCRIPT DOES NOT MOVE, ON PURPOSE:
  - app/data/reference_boqs/*.xlsx and app/data/work_orders/*.pdf -- the
    raw uploaded source documents. tests/golden/*.json's _meta.source_path
    pins exact paths to these files; moving them would break Workstream
    00's regression tests for zero storage-correctness benefit, since
    it's the DERIVED data (extractions, metadata, item-code datasets)
    that actually needs to be per-company, not a fixture every golden
    test already knows how to find.
  - app/data/ice_db/emission_factors.json, app/services/ice_factors.py's
    data -- these are global, sourced IFC/CEA data every company should
    see the same audited numbers from. Only Provident's own item-code
    mapping and project history are company-specific.

USAGE (from backend/):
    python scripts/migrate_to_company_storage.py            # dry run --
                                                              # prints what
                                                              # would move,
                                                              # touches nothing
    python scripts/migrate_to_company_storage.py --write     # actually moves

Safe to re-run: any destination file that already exists is left alone
and reported, never silently overwritten -- if you need to re-migrate a
single file, remove that specific destination file first.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import company_store  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parent.parent
COMPANY_ID = company_store.DEFAULT_COMPANY_ID  # "provident" -- the only company this migration ever targets

# (source, destination) pairs for the two single-file moves.
SINGLE_FILE_MOVES = [
    (
        BACKEND_ROOT / "app" / "data" / "master_item_codes" / "master_item_code_factors.json",
        company_store.master_item_codes_path(COMPANY_ID),
    ),
    (
        BACKEND_ROOT / "app" / "data" / "master_item_codes" / "master_item_code_factors_pre_workstream01_backup.json",
        company_store.company_dir(COMPANY_ID) / "master_item_code_factors_pre_workstream01_backup.json",
    ),
    (
        BACKEND_ROOT / "app" / "data" / "reference_boqs" / "reference_stats.json",
        company_store.reference_projects_dir(COMPANY_ID) / "reference_stats.json",
    ),
]

# Directories whose *.json contents move file-by-file into a new directory.
DIRECTORY_MOVES = [
    (
        BACKEND_ROOT / "app" / "data" / "reference_boqs" / "cache",
        company_store.reference_projects_cache_dir(COMPANY_ID),
    ),
    (
        BACKEND_ROOT / "app" / "data" / "projects",
        company_store.projects_dir(COMPANY_ID),
    ),
]


def _plan_single_files() -> list[tuple[Path, Path, str]]:
    plan = []
    for src, dst in SINGLE_FILE_MOVES:
        if not src.exists():
            plan.append((src, dst, "SKIP -- source not found"))
        elif dst.exists():
            plan.append((src, dst, "SKIP -- destination already exists"))
        else:
            plan.append((src, dst, "MOVE"))
    return plan


def _plan_directories() -> list[tuple[Path, Path, str]]:
    plan = []
    for src_dir, dst_dir in DIRECTORY_MOVES:
        if not src_dir.exists():
            plan.append((src_dir, dst_dir, "SKIP -- source directory not found"))
            continue
        for src in sorted(src_dir.glob("*.json")):
            dst = dst_dir / src.name
            if dst.exists():
                plan.append((src, dst, "SKIP -- destination already exists"))
            else:
                plan.append((src, dst, "MOVE"))
    return plan


def _inject_company_id(path: Path) -> None:
    """For a migrated project JSON file only: adds an explicit
    "company_id": "provident" key if the file doesn't already carry one,
    so the file is self-describing rather than relying on
    ProjectSchema's default forever.
    """
    with open(path, "r") as f:
        data = json.load(f)
    if "company_id" not in data:
        data["company_id"] = COMPANY_ID
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Actually move files (default: dry run)")
    args = parser.parse_args()

    single_plan = _plan_single_files()
    dir_plan = _plan_directories()
    full_plan = single_plan + dir_plan

    print(f"{'WRITE' if args.write else 'DRY RUN'} -- migrating to data/companies/{COMPANY_ID}/\n")
    for src, dst, action in full_plan:
        rel_src = src.relative_to(BACKEND_ROOT) if src.is_relative_to(BACKEND_ROOT) else src
        rel_dst = dst.relative_to(BACKEND_ROOT) if dst.is_relative_to(BACKEND_ROOT) else dst
        print(f"  [{action:^32s}] {rel_src}  ->  {rel_dst}")

    n_to_move = sum(1 for _, _, action in full_plan if action == "MOVE")
    print(f"\n{n_to_move} file(s) to move.")

    if not args.write:
        print("\nDry run only -- nothing was touched. Re-run with --write to apply.")
        return

    projects_src_dir = BACKEND_ROOT / "app" / "data" / "projects"

    for src, dst, action in full_plan:
        if action != "MOVE":
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        if src.parent == projects_src_dir:
            _inject_company_id(dst)

    print(f"\nDone. Moved {n_to_move} file(s) into data/companies/{COMPANY_ID}/.")
    print(
        "Any SKIPped source directories/files above (data/projects/, "
        "app/data/reference_boqs/cache/, etc.) are left in place even if "
        "now empty -- delete them by hand once you've confirmed the move."
    )


if __name__ == "__main__":
    main()