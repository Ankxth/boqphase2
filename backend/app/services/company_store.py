"""Workstream 04: company-scoped storage roots.

Everything this project persists at runtime -- a Phase 1 project record
(project_store.py), a reference project's metadata + cached BOQ
extraction (reference_store.py / boq_cache.py), and a company's own
item-code dataset (previously the single global
app/data/master_item_codes/master_item_code_factors.json) -- used to
live in one global location, shared by every user of the app. That's
fine for one company; it's wrong for the "not specifically for Provident
but for other companies too" product this is becoming, since company
B's Phase 1 estimates would otherwise learn from company A's reference
projects, and a Work Order upload would have nowhere to look but
Provident's own item-code dataset.

This module is the single place that knows where a given company's data
lives on disk -- the same role project_store.py's own docstring already
described for itself ("swapping this for a real database later means
changing only this file"), just one level up. Every other storage
module (project_store, boq_cache, reference_store) and every API
endpoint that touches persisted data resolves its paths through here,
never by constructing a `data/companies/...` path itself.

Deliberately storage-only, per Workstream 04's scope: this introduces
WHERE a company's data lives, not any new classification or calculation
logic -- that's Workstream 05 (the onboarding pipeline that actually
populates a new company's master_item_codes.json).

Layout
------
data/companies/<company_id>/
    projects/<project_id>.json         -- Phase 1 project records (was data/projects/)
    reference_projects/
        reference_stats.json           -- was data/reference_boqs/reference_stats.json
        cache/<slug>.json              -- was data/reference_boqs/cache/
    master_item_codes.json             -- was app/data/master_item_codes/master_item_code_factors.json

What does NOT move: the raw uploaded source documents themselves
(app/data/reference_boqs/*.xlsx, app/data/work_orders/*.pdf) stay where
they are. They're read-only fixtures the golden-file tests pin exact
paths to (see tests/golden/*.json's _meta.source_path) -- moving them
would be a test-breaking change for zero storage-correctness benefit,
since it's the DERIVED data (extractions, metadata, item-code datasets)
that actually needs to be per-company, not the original file someone
uploaded.
"""

from __future__ import annotations

from pathlib import Path

# The one company this project has ever served. Every existing project
# record, reference project, and the existing master_item_code_factors.json
# belong to Provident -- see scripts/migrate_to_company_storage.py, which
# moves them here under this exact id. Every storage function in this
# codebase defaults to this company_id so nothing that already works
# breaks by omission; a caller only needs to pass a different company_id
# once a second company's data actually exists.
DEFAULT_COMPANY_ID = "provident"

COMPANIES_DIR = Path(__file__).resolve().parent.parent / "data" / "companies"


def company_dir(company_id: str) -> Path:
    return COMPANIES_DIR / company_id


def projects_dir(company_id: str) -> Path:
    return company_dir(company_id) / "projects"


def reference_projects_dir(company_id: str) -> Path:
    return company_dir(company_id) / "reference_projects"


def reference_projects_cache_dir(company_id: str) -> Path:
    return reference_projects_dir(company_id) / "cache"


def master_item_codes_path(company_id: str) -> Path:
    return company_dir(company_id) / "master_item_codes.json"


def onboarding_jobs_dir(company_id: str) -> Path:
    """Workstream 05: where a company's onboarding-pipeline job records
    live -- one JSON file per upload, holding the ingested/deduped/
    classified rows, the impact-ranked review queue, and (once a human
    has reviewed it) the confirmed decisions. See
    app/services/onboarding/pipeline.py.
    """
    return company_dir(company_id) / "onboarding_jobs"


def onboarding_job_path(company_id: str, job_id: str) -> Path:
    return onboarding_jobs_dir(company_id) / f"{job_id}.json"


def project_dir(company_id: str, project_id: str) -> Path:
    """Workstream 10: a per-project DIRECTORY for Phase 3 data (bills,
    the Phase 3 baseline) -- deliberately separate from
    projects_dir(company_id) / f"{project_id}.json" (the Phase 1 project
    record FILE projects_dir() already resolves via project_store.py).
    The two coexist without colliding: 'projects/<id>.json' is a file,
    'projects/<id>/' is a directory -- same parent, different path shape,
    same convention project_store.py's own docstring already established
    ("swapping this for a real database later means changing only this
    file").
    """
    return projects_dir(company_id) / project_id


def phase3_baseline_path(company_id: str, project_id: str) -> Path:
    return project_dir(company_id, project_id) / "phase3_baseline.json"


def project_bills_dir(company_id: str, project_id: str) -> Path:
    return project_dir(company_id, project_id) / "bills"


def project_bill_path(company_id: str, project_id: str, period: str) -> Path:
    return project_bills_dir(company_id, project_id) / f"{period}.json"


def canonical_categories_path() -> Path:
    """Workstream 05: the ONE thing in this module that is deliberately
    NOT company-scoped. A company's own item-code -> category mapping is
    private to that company (master_item_codes_path, above); but the
    material-category taxonomy itself (what "steel_structural" or
    "plaster (gypsum)" even means, and its sourced emission factor) is
    the same physical reality for every company and should be shared and
    grown together, not reinvented per company -- see
    app/services/onboarding/canonical_categories.py.

    Deliberately derived from COMPANIES_DIR.parent (not a separate
    hardcoded path) so that tests which monkeypatch COMPANIES_DIR (see
    tests/test_company_storage.py's isolated_company_storage fixture)
    automatically isolate this path too, without needing a second
    monkeypatch.
    """
    return COMPANIES_DIR.parent / "canonical_material_categories.json"


def list_company_ids() -> list[str]:
    """Every company with at least one file under data/companies/ --
    not a registry of "valid" companies, just what's actually on disk.
    """
    if not COMPANIES_DIR.exists():
        return []
    return sorted(p.name for p in COMPANIES_DIR.iterdir() if p.is_dir())