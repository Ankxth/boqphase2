"""Loader for the material substitution catalog -- see
app/data/ice_db/substitution_catalog.json for the seed data and its own
notes on why it's currently limited to cement blends and brick->block
(the only substitutions with a real sourced factor on both sides right
now; recycled-steel and low-VOC-paint substitutions are deliberately
left out until a real figure is sourced for either).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

CATALOG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "ice_db" / "substitution_catalog.json"
)


def load_catalog() -> list[dict]:
    with open(CATALOG_PATH, "r") as f:
        data = json.load(f)
    return data["substitutions"]


def get_substitution(substitution_id: str) -> Optional[dict]:
    for entry in load_catalog():
        if entry["id"] == substitution_id:
            return entry
    return None


def list_substitutions_for_category(base_category: str) -> list[dict]:
    """All catalog entries whose base_category matches -- what the
    frontend would show as available substitution options for a given
    material category found in a calculated BOQ result."""
    return [e for e in load_catalog() if e["base_category"] == base_category]
