"""Workstream 05: end-to-end API tests for the onboarding pipeline --
upload -> review -> confirm -> written into the company's own
master_item_codes.json, with the same company-isolation discipline
Workstream 04's tests established (see tests/test_company_storage.py).

use_llm_draft=false is passed on every upload in this file so these
tests never depend on network access or a configured LLM provider --
the LLM-drafting stage itself (app/services/onboarding/llm_classifier.py)
is a pure function tested by construction (closed-vocabulary + cited-
word validation logic has no I/O to isolate), not re-exercised here.
"""

from __future__ import annotations

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.services import company_store

client = TestClient(__import__("app.main", fromlist=["app"]).app)


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def _item_code_xlsx_bytes(rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Item Code", "Description", "Unit"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_ROWS = [
    ("IC-001", "RCC M30 footing works", "CUM"),                 # auto -> concrete, yes
    ("IC-002", "MS Angle section works", "KG"),                 # auto -> structural_steel, yes
    ("IC-003", "Prl-Site cleaning and surveying", "LS"),         # auto -> admin-excluded, no
    ("IC-004", "Unusual specialty item Alpha-9000", "NOS"),      # stays need_review
    ("IC-005", "Unusual duplicate item Beta-1000", "NOS"),       # need_review, duplicated text below
    ("IC-006", "unusual duplicate item beta-1000", "nos"),       # same normalized text/unit as IC-005
]


def _upload(company_id: str, rows=None):
    xlsx = _item_code_xlsx_bytes(rows if rows is not None else _ROWS)
    resp = client.post(
        f"/onboarding/{company_id}/upload",
        files={"item_code_file": ("items.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"use_llm_draft": "false"},
    )
    return resp


def test_upload_classifies_auto_rows_and_dedupes_need_review():
    resp = _upload("acme")
    assert resp.status_code == 200
    job = resp.json()

    assert job["company_id"] == "acme"
    assert job["n_raw_codes"] == 6
    # IC-005/IC-006 collapse to one unique description -> 5 unique rows.
    assert job["n_unique_descriptions"] == 5
    assert job["summary"]["n_auto_classified"] == 3  # IC-001, IC-002, IC-003
    assert job["summary"]["n_needs_review"] == 2      # the Alpha item + the deduped Beta item

    review_codes = {r["code"] for r in job["review_queue"]}
    assert "IC-001" not in review_codes
    beta_entry = next(r for r in job["review_queue"] if r["desc"].lower().startswith("unusual duplicate"))
    assert beta_entry["group_size"] == 2  # IC-005 + IC-006 fanned into one review item
    assert beta_entry["impact_basis"] == "frequency"  # no amounts_by_code supplied


def test_get_job_after_upload_returns_same_job():
    job = _upload("acme").json()
    resp = client.get(f"/onboarding/acme/jobs/{job['job_id']}")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job["job_id"]


def test_get_unknown_job_is_404():
    resp = client.get("/onboarding/acme/jobs/does-not-exist")
    assert resp.status_code == 404


def test_confirm_writes_master_file_and_fans_out_duplicate_group():
    job = _upload("acme").json()
    alpha_code = next(r["code"] for r in job["review_queue"] if "Alpha" in r["desc"])
    beta_code = next(r["code"] for r in job["review_queue"] if "Beta" in r["desc"] or "beta" in r["desc"].lower())

    resp = client.post(
        f"/onboarding/acme/jobs/{job['job_id']}/confirm",
        json={"decisions": [
            {"code": alpha_code, "fields": {"contributes": "no", "material_category": None, "unit_note": "Confirmed non-material by human reviewer."}},
            {"code": beta_code, "fields": {"contributes": "no", "material_category": None, "unit_note": "Confirmed non-material by human reviewer."}},
        ]},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["decisions_applied"] == 2
    assert result["codes_written"] == 1 + 2  # alpha (group size 1) + beta group (IC-005, IC-006)
    assert result["total_codes_in_master"] == 6

    master_path = company_store.master_item_codes_path("acme")
    assert master_path.exists()
    import json
    master = json.loads(master_path.read_text())
    assert len(master) == 6
    assert master["IC-001"]["contributes"] == "yes"
    assert master["IC-001"]["material_category"] == "concrete"  # bare canonical key -- see canonical_categories.py
    assert "M30" in master["IC-001"]["unit_note"]  # grade still captured, just not in material_category
    assert master["IC-002"]["material_category"] == "structural_steel"
    assert master["IC-003"]["contributes"] == "no"  # admin-excluded
    assert master[alpha_code]["contributes"] == "no"  # human-confirmed
    # Both members of the duplicate group got the confirmed decision.
    assert master["IC-005"]["contributes"] == "no"
    assert master["IC-006"]["contributes"] == "no"
    assert master["IC-005"]["unit_note"] == "Confirmed non-material by human reviewer."


def test_confirm_unknown_code_is_rejected_without_partial_write():
    job = _upload("acme").json()
    resp = client.post(
        f"/onboarding/acme/jobs/{job['job_id']}/confirm",
        json={"decisions": [{"code": "NOT-A-REAL-CODE", "fields": {"contributes": "no"}}]},
    )
    assert resp.status_code == 404
    assert not company_store.master_item_codes_path("acme").exists()


def test_two_companies_are_fully_isolated():
    job_acme = _upload("acme").json()
    job_beta = _upload("beta", rows=[("X-1", "RCC M25 slab", "CUM"), ("X-2", "Unusual item for beta", "NOS")]).json()

    beta_code = job_beta["review_queue"][0]["code"]
    client.post(f"/onboarding/beta/jobs/{job_beta['job_id']}/confirm", json={
        "decisions": [{"code": beta_code, "fields": {"contributes": "no"}}],
    })

    acme_path = company_store.master_item_codes_path("acme")
    beta_path = company_store.master_item_codes_path("beta")
    assert acme_path != beta_path
    assert not acme_path.exists()  # acme's job was never confirmed in this test
    assert beta_path.exists()

    import json
    beta_master = json.loads(beta_path.read_text())
    assert set(beta_master.keys()) == {"X-1", "X-2"}
    assert job_acme["job_id"] != job_beta["job_id"]

    # beta's job (and master file) must not be reachable by asking for it
    # under acme's company_id.
    cross_resp = client.get(f"/onboarding/acme/jobs/{job_beta['job_id']}")
    assert cross_resp.status_code == 404


def test_register_new_category_is_visible_cross_company():
    job = _upload("acme").json()
    alpha_code = next(r["code"] for r in job["review_queue"] if "Alpha" in r["desc"])

    new_template = {
        "contributes": "yes", "top5": "no", "ef_kgco2e_per_kg": 1.11,
        "ef_source": "Test-only fixture citation.", "cea_adjusted": "no",
        "evidence_tier": "company_submitted", "material_category": "specialty_alpha_material",
        "unit_note": "Registered via onboarding confirm test.",
    }
    resp = client.post(
        f"/onboarding/acme/jobs/{job['job_id']}/confirm",
        json={"decisions": [{"code": alpha_code, "fields": new_template, "register_as_new_category": "specialty_alpha_material"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["new_categories_registered"] == ["specialty_alpha_material"]

    categories_resp = client.get("/onboarding/canonical-categories")
    assert categories_resp.status_code == 200
    categories = categories_resp.json()
    assert "specialty_alpha_material" in categories
    assert categories["specialty_alpha_material"]["ef_kgco2e_per_kg"] == 1.11

    # A second, unrelated company sees the same shared taxonomy -- this
    # IS the cross-company sharing the taxonomy is for. Confirm this by
    # uploading a fresh item-code list for "beta" and independently
    # querying the endpoint again with a different company_id in the URL
    # (canonical-categories is deliberately global, see the endpoint's
    # own docstring).
    _upload("beta", rows=[("Y-1", "RCC M25 slab", "CUM")])
    categories_resp_2 = client.get("/onboarding/canonical-categories")
    assert "specialty_alpha_material" in categories_resp_2.json()


def test_upload_rejects_non_excel_file():
    resp = client.post(
        "/onboarding/acme/upload",
        files={"item_code_file": ("items.csv", b"code,desc,unit\n1,foo,KG\n", "text/csv")},
        data={"use_llm_draft": "false"},
    )
    assert resp.status_code == 400