"""Cache store for BOQ extraction results.

Each processed BOQ becomes one JSON record under
data/companies/<company_id>/reference_projects/cache/, keyed by a
project slug. This is the "reference/cache memory" the extraction
engine writes to, and what boq_match.py reads from -- it replaces the
old single hardcoded reference_stats.json for quantity data
(reference_stats.json now holds only non-extractable metadata like GFA).

Workstream 04: scoped per company via app.services.company_store,
same reasoning as project_store.py -- company B's reference projects
must not show up as match candidates for company A's Phase 1 estimates.
Every function defaults to company_store.DEFAULT_COMPANY_ID so existing
single-company callers (including the standalone scripts) keep working
unchanged.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.services import company_store


def save_extraction(
    project_slug: str, extraction: dict, company_id: str = company_store.DEFAULT_COMPANY_ID
) -> Path:
    cache_dir = company_store.reference_projects_cache_dir(company_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "project_slug": project_slug,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        **extraction,
    }
    path = cache_dir / f"{project_slug}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    return path


def load_extraction(project_slug: str, company_id: str = company_store.DEFAULT_COMPANY_ID) -> Optional[dict]:
    path = company_store.reference_projects_cache_dir(company_id) / f"{project_slug}.json"
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)


def list_cached_projects(company_id: str = company_store.DEFAULT_COMPANY_ID) -> list[str]:
    cache_dir = company_store.reference_projects_cache_dir(company_id)
    if not cache_dir.exists():
        return []
    return [p.stem for p in cache_dir.glob("*.json")]