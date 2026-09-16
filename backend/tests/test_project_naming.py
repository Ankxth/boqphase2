"""Workstream 11: tests for project_name -- the human-readable label added
to ProjectSchema (app/schemas/project_schema.py) and threaded through the
tiered-form API (app/api/form.py) so Phase 3's project listing
(app/services/phase3.py's list_projects()) has something better than a
raw project_id to show a user picking from their projects.

Isolated the same way every other WS04-onward test isolates storage:
company_store.COMPANIES_DIR redirected to a pytest tmp_path.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import company_store, project_store

client = TestClient(__import__("app.main", fromlist=["app"]).app)

COMPANY = "provident"


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def _submit(project_name=None, **overrides):
    payload = {
        "gfa_sqm": 30000,
        "location": "Chennai",
        "structural_system_type": "rcc_frame",
        "company_id": COMPANY,
    }
    if project_name is not None:
        payload["project_name"] = project_name
    payload.update(overrides)
    return client.post("/form", json=payload)


def test_form_persists_project_name():
    r = _submit(project_name="Ecopolitan Phase 2")
    assert r.status_code == 200
    body = r.json()
    assert body["project_name"] == "Ecopolitan Phase 2"

    pid = body["project_id"]
    loaded = project_store.load_project(pid, company_id=COMPANY)
    assert loaded.project_name == "Ecopolitan Phase 2"


def test_form_project_name_defaults_to_none_when_omitted():
    r = _submit()  # no project_name at all
    assert r.status_code == 200
    assert r.json()["project_name"] is None


def test_get_project_returns_the_saved_name():
    pid = _submit(project_name="Botanico Residences").json()["project_id"]
    r = client.get(f"/form/{pid}", params={"company_id": COMPANY})
    assert r.status_code == 200
    assert r.json()["project_name"] == "Botanico Residences"


def test_patch_updates_project_name_without_disturbing_other_fields():
    pid = _submit(project_name="Working Title").json()["project_id"]

    r = client.patch(f"/form/{pid}", json={"project_name": "Final Name", "company_id": COMPANY})
    assert r.status_code == 200
    body = r.json()
    assert body["project_name"] == "Final Name"
    # Untouched tiered fields survive the rename unchanged.
    assert body["mandatory"]["gfa_sqm"]["value"] == 30000
    assert body["mandatory"]["location"]["value"] == "Chennai"


def test_patch_without_project_name_leaves_existing_name_untouched():
    pid = _submit(project_name="Do Not Change Me").json()["project_id"]

    r = client.patch(f"/form/{pid}", json={"gfa_sqm": 35000, "company_id": COMPANY})
    assert r.status_code == 200
    body = r.json()
    assert body["project_name"] == "Do Not Change Me"
    assert body["mandatory"]["gfa_sqm"]["value"] == 35000


def test_pre_workstream_11_project_file_loads_without_a_project_name():
    # Simulates a project JSON saved before this field existed -- no
    # "project_name" key at all in the persisted dict. Backward
    # compatibility the same way company_id's own WS04 migration worked.
    import json

    projects_dir = company_store.projects_dir(COMPANY)
    projects_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = projects_dir / "legacy-proj.json"
    legacy_path.write_text(json.dumps({
        "project_id": "legacy-proj",
        "company_id": COMPANY,
        "mandatory": {
            "gfa_sqm": {"value": 20000, "source": "user-entered", "confidence": 1.0},
            "location": {"value": None, "source": "unset", "confidence": 0.0},
            "structural_system_type": {"value": None, "source": "unset", "confidence": 0.0},
        },
        "tier2": {},
        "tier3": {},
    }))

    loaded = project_store.load_project("legacy-proj", company_id=COMPANY)
    assert loaded is not None
    assert loaded.project_name is None
    assert loaded.mandatory.gfa_sqm.value == 20000