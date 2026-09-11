"""Simple file-based project persistence.

This is the piece that was missing to make any of the built services
reachable over HTTP across multiple requests -- without this, a
frontend could POST a form in one request and have nowhere to store the
result for a second request (calculate, substitute, etc.) to find.

One JSON file per project under data/projects/<project_id>.json --
same pattern already used for the reference BOQ extraction cache
(boq_cache.py). Not a real database; fine for single-server development
and testing. DATABASE_URL in config.py is still empty -- swapping this
for a real database later means changing only this file, since every
API endpoint goes through save_project()/load_project(), never touches
the filesystem directly.

Handles _derived explicitly: it's an ad-hoc dict attribute on
ProjectSchema instances (not a declared Pydantic field, used by
boq_match.py, project_boq_refinement.py, and calculation_engine.py to
pass computed values like concrete_vol_per_sqm between stages), so it
needs to be serialized/restored alongside the model's real fields
rather than relying on model_dump() to capture it automatically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.schemas.project_schema import ProjectSchema

PROJECTS_DIR = Path(__file__).resolve().parent.parent / "data" / "projects"


def save_project(project: ProjectSchema) -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    data = project.model_dump(mode="json")
    data["_derived"] = project.__dict__.get("_derived", {})
    path = PROJECTS_DIR / f"{project.project_id}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_project(project_id: str) -> Optional[ProjectSchema]:
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        return None
    with open(path, "r") as f:
        data = json.load(f)
    derived = data.pop("_derived", {})
    project = ProjectSchema.model_validate(data)
    project.__dict__["_derived"] = derived
    return project


def delete_project(project_id: str) -> bool:
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def list_project_ids() -> list[str]:
    if not PROJECTS_DIR.exists():
        return []
    return [p.stem for p in PROJECTS_DIR.glob("*.json")]