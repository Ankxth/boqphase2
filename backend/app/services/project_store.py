"""Simple file-based project persistence.

This is the piece that was missing to make any of the built services
reachable over HTTP across multiple requests -- without this, a
frontend could POST a form in one request and have nowhere to store the
result for a second request (calculate, substitute, etc.) to find.

One JSON file per project under
data/companies/<company_id>/projects/<project_id>.json -- same pattern
already used for the reference BOQ extraction cache (boq_cache.py). Not
a real database; fine for single-server development and testing.
DATABASE_URL in config.py is still empty -- swapping this for a real
database later means changing only this file, since every API endpoint
goes through save_project()/load_project(), never touches the
filesystem directly.

Workstream 04: paths now go through app.services.company_store instead
of a single hardcoded data/projects/ directory (see that module's
docstring for why). save_project() reads the company to save under
straight off the project itself (project.company_id) -- a project
always knows which company it belongs to once it exists, so there's
nothing for the caller to get wrong there. load_project() is the one
function that genuinely needs company_id passed in: you can't know
which company's directory to look in for a project you haven't loaded
yet. It defaults to company_store.DEFAULT_COMPANY_ID so every existing
caller that doesn't know about companies yet keeps working exactly as
before.

Handles _derived explicitly: it's an ad-hoc dict attribute on
ProjectSchema instances (not a declared Pydantic field, used by
boq_match.py, project_boq_refinement.py, and calculation_engine.py to
pass computed values like concrete_vol_per_sqm between stages), so it
needs to be serialized/restored alongside the model's real fields
rather than relying on model_dump() to capture it automatically.
"""

from __future__ import annotations

import json
from typing import Optional

from app.schemas.project_schema import ProjectSchema
from app.services import company_store


def save_project(project: ProjectSchema) -> None:
    projects_dir = company_store.projects_dir(project.company_id)
    projects_dir.mkdir(parents=True, exist_ok=True)
    data = project.model_dump(mode="json")
    data["_derived"] = project.__dict__.get("_derived", {})
    path = projects_dir / f"{project.project_id}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_project(project_id: str, company_id: str = company_store.DEFAULT_COMPANY_ID) -> Optional[ProjectSchema]:
    path = company_store.projects_dir(company_id) / f"{project_id}.json"
    if not path.exists():
        return None
    with open(path, "r") as f:
        data = json.load(f)
    derived = data.pop("_derived", {})
    project = ProjectSchema.model_validate(data)
    project.__dict__["_derived"] = derived
    return project


def delete_project(project_id: str, company_id: str = company_store.DEFAULT_COMPANY_ID) -> bool:
    path = company_store.projects_dir(company_id) / f"{project_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def list_project_ids(company_id: str = company_store.DEFAULT_COMPANY_ID) -> list[str]:
    projects_dir = company_store.projects_dir(company_id)
    if not projects_dir.exists():
        return []
    return [p.stem for p in projects_dir.glob("*.json")]