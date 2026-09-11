"""Cache store for BOQ extraction results.

Each processed BOQ becomes one JSON record under data/reference_boqs/cache/,
keyed by a project slug. This is the "reference/cache memory" the
extraction engine writes to, and what boq_match.py reads from -- it
replaces the old single hardcoded reference_stats.json for quantity data
(reference_stats.json now holds only non-extractable metadata like GFA).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "reference_boqs" / "cache"


def save_extraction(project_slug: str, extraction: dict) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "project_slug": project_slug,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        **extraction,
    }
    path = CACHE_DIR / f"{project_slug}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    return path


def load_extraction(project_slug: str) -> Optional[dict]:
    path = CACHE_DIR / f"{project_slug}.json"
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)


def list_cached_projects() -> list[str]:
    if not CACHE_DIR.exists():
        return []
    return [p.stem for p in CACHE_DIR.glob("*.json")]