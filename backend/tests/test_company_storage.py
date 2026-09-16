"""Workstream 04: tests for company-scoped storage.

Nothing covered the storage layer at all before this (the golden-file
tests are read-only fixtures, never save_project/register_reference
data). These tests write real files, so every one of them redirects
company_store.COMPANIES_DIR to a pytest tmp_path first -- never touching
the real app/data/companies/provident/ tree an actual user's data lives
in. That redirect works because every storage function (project_store,
boq_cache, reference_store) resolves paths through company_store.*() at
call time, not at import time -- monkeypatching the one module attribute
is enough to isolate all three.

The core thing under test: two companies' data must never leak into
each other -- a reference project registered for company A must not be
a match candidate for company B's Phase 1 estimate, and a project saved
under company A must not be loadable by asking for it under company B.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.schemas.project_schema import (
    FieldValue,
    MandatoryFields,
    ProjectSchema,
    StructuralSystemType,
)
from app.services import boq_cache, company_store, project_store, reference_store

client = TestClient(__import__("app.main", fromlist=["app"]).app)


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    """Every test in this file gets its own throwaway data/companies/
    directory -- see module docstring for why this is safe to do via a
    single monkeypatch.
    """
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def _project(project_id: str, company_id: str) -> ProjectSchema:
    return ProjectSchema(
        project_id=project_id,
        company_id=company_id,
        mandatory=MandatoryFields(
            gfa_sqm=FieldValue(value=50000.0, source="user-entered", confidence=1.0),
        ),
    )


def test_company_store_paths_are_scoped_per_company():
    assert company_store.projects_dir("acme") != company_store.projects_dir("beta")
    assert company_store.projects_dir("acme").parent == company_store.company_dir("acme")


def test_project_store_round_trip_is_company_scoped():
    project_store.save_project(_project("proj-1", "acme"))

    loaded_same_company = project_store.load_project("proj-1", company_id="acme")
    assert loaded_same_company is not None
    assert loaded_same_company.company_id == "acme"
    assert loaded_same_company.mandatory.gfa_sqm.value == 50000.0

    # Same project_id, wrong company -- must NOT be found. This is the
    # whole point of Workstream 04: a project_id alone is not enough to
    # find a project once storage is multi-tenant.
    loaded_wrong_company = project_store.load_project("proj-1", company_id="beta")
    assert loaded_wrong_company is None


def test_project_missing_company_id_defaults_to_provident():
    # A pre-Workstream-04 JSON file has no "company_id" key at all --
    # ProjectSchema.company_id's default ("provident") must fill it in
    # on load, not raise a validation error.
    project = ProjectSchema.model_validate({"project_id": "legacy-1", "mandatory": {}})
    assert project.company_id == "provident"


def test_reference_store_candidates_do_not_cross_companies():
    reference_store.upsert_metadata(
        "acme_tower", structural_system_type="rcc_frame", typology="residential",
        gfa_sqm=40000.0, company_id="acme",
    )
    boq_cache.save_extraction("acme_tower", {"materials": {}}, company_id="acme")

    acme_candidates = reference_store.find_candidates(structural_system_type="rcc_frame", company_id="acme")
    beta_candidates = reference_store.find_candidates(structural_system_type="rcc_frame", company_id="beta")

    assert len(acme_candidates) == 1
    assert acme_candidates[0]["slug"] == "acme_tower"
    assert beta_candidates == []


def test_form_api_defaults_to_provident_when_company_id_omitted():
    resp = client.post("/form", json={"gfa_sqm": 45000.0, "structural_system_type": "rcc_frame"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["company_id"] == "provident"

    # Findable via GET without passing company_id (default matches what
    # POST /form used).
    get_resp = client.get(f"/form/{body['project_id']}")
    assert get_resp.status_code == 200


def test_form_api_respects_explicit_company_id_and_isolates_lookup():
    resp = client.post(
        "/form", json={"company_id": "acme", "gfa_sqm": 45000.0, "structural_system_type": "rcc_frame"}
    )
    assert resp.status_code == 200
    project_id = resp.json()["project_id"]
    assert resp.json()["company_id"] == "acme"

    # Right company -- found.
    ok = client.get(f"/form/{project_id}", params={"company_id": "acme"})
    assert ok.status_code == 200

    # Default company (provident) -- NOT found, since this project lives
    # under acme's own directory.
    wrong = client.get(f"/form/{project_id}")
    assert wrong.status_code == 404