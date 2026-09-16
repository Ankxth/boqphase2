"""Workstream 05: top-level onboarding orchestration.

Ties every stage together into the shape the roadmap described: ingest
&amp; extract (ingest.py, called by the API layer before this module),
deduplicate to unique descriptions (ingest.dedupe_by_description),
cheap regex pass first (classification_pipeline.run_classification_pass),
LLM draft only for the remainder (llm_classifier.draft_categories, plus
similarity_triage's TF-IDF suggestion as a second, free, local-only
opinion alongside it), impact-ranked human review (this module's
review-queue construction), and confirmed answers feed forward into a
shared cross-company reference set (confirm_onboarding_job, which writes
into the company's own master_item_codes.json and, only on explicit
request, canonical_categories' shared taxonomy).

Nothing here ever writes to a company's live master_item_codes.json
except confirm_onboarding_job -- run_onboarding_upload only ever
produces a job record for a human to review, same "never auto-apply an
unreviewed classification" discipline the rest of this project already
follows for substitution suggestions and LLM tier estimates.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from app.services import company_store
from app.services.onboarding import canonical_categories
from app.services.onboarding.classification_pipeline import run_classification_pass
from app.services.onboarding.ingest import dedupe_by_description
from app.services.onboarding.llm_classifier import draft_categories
from app.services.onboarding.similarity_triage import rank_similarity


def _new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def _impact_for(rep_code: str, code_groups: dict[str, list[str]], amounts_by_code: Optional[dict[str, float]]) -> tuple[float, str]:
    member_codes = code_groups.get(rep_code, [rep_code])
    if amounts_by_code:
        total = sum(amounts_by_code.get(c, 0.0) for c in member_codes)
        return total, "amount"
    # No amounts available (e.g. an item-code list uploaded on its own,
    # with no paired priced document) -- frequency of occurrence across
    # the raw dataset is the best available impact proxy: a description
    # collapsed from many original codes is more likely to matter to the
    # final total than one that appears once.
    return float(len(member_codes)), "frequency"


def run_onboarding_upload(
    company_id: str,
    raw_rows: dict[str, dict],
    amounts_by_code: Optional[dict[str, float]] = None,
    use_llm_draft: bool = True,
) -> dict:
    """raw_rows: code -> row dict, already parsed by ingest.parse_item_code_workbook
    (or built directly, e.g. by a test). amounts_by_code: optional code ->
    Rs amount map from a paired priced document (a BOQ or Work Order for
    the same items), used to impact-rank the review queue by real money
    instead of raw frequency when available.
    """
    dedupe = dedupe_by_description(raw_rows)
    working = {code: dict(row) for code, row in dedupe.deduped.items()}

    log = run_classification_pass(working)

    still_need_review = {c: r for c, r in working.items() if (r.get("contributes") or "").strip().lower() == "need_review"}

    llm_drafts: dict[str, dict] = {}
    if use_llm_draft and still_need_review:
        canonical_keys = list(canonical_categories.load_canonical_categories().keys())
        drafts = draft_categories(still_need_review, canonical_keys)
        llm_drafts = {code: asdict(d) for code, d in drafts.items()}

    # Similarity triage: a second, free, purely-local opinion (no LLM
    # call) -- assistive only, exactly like the original script. Runs
    # against the WHOLE working set (not just still_need_review) since it
    # needs already-"yes" rows from Step B as its comparison pool; a
    # brand-new company's first-ever upload may have few or no "yes" rows
    # yet, in which case this returns [] and simply adds nothing, which
    # is the expected, honest result rather than an error.
    similarity_by_code = {r["code"]: r for r in rank_similarity(working)}

    review_queue = []
    for code, row in still_need_review.items():
        impact, impact_basis = _impact_for(code, dedupe.code_groups, amounts_by_code)
        review_queue.append({
            "code": code,
            "desc": row.get("desc"),
            "unit": row.get("unit"),
            "group_size": len(dedupe.code_groups.get(code, [code])),
            "impact": impact,
            "impact_basis": impact_basis,
            "llm_draft": llm_drafts.get(code),
            "similarity_suggestion": similarity_by_code.get(code),
        })
    review_queue.sort(key=lambda r: -r["impact"])

    job = {
        "job_id": _new_job_id(),
        "company_id": company_id,
        "status": "pending_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_raw_codes": len(raw_rows),
        "n_unique_descriptions": len(dedupe.deduped),
        "code_groups": dedupe.code_groups,
        "rows": working,
        "review_queue": review_queue,
        "classification_log_summary": log.to_summary_dict(),
        "summary": {
            "n_auto_classified": sum(1 for r in working.values() if (r.get("contributes") or "").strip().lower() != "need_review"),
            "n_needs_review": len(still_need_review),
            "n_llm_drafted": len(llm_drafts),
            "n_similarity_suggested": len(similarity_by_code),
        },
    }
    _save_job(company_id, job)
    return job


def _save_job(company_id: str, job: dict) -> None:
    path = company_store.onboarding_job_path(company_id, job["job_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job, indent=2))


def load_job(company_id: str, job_id: str) -> Optional[dict]:
    path = company_store.onboarding_job_path(company_id, job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def confirm_onboarding_job(company_id: str, job_id: str, decisions: list[dict]) -> dict:
    """decisions: [{"code": <representative code from the review queue>,
    "fields": {<master-row fields to set, e.g. contributes/material_category/
    ef_kgco2e_per_kg/ef_source/cea_adjusted/evidence_tier/unit_note>},
    "register_as_new_category": <optional canonical-taxonomy key to
    register this template under, for future companies' regex/LLM passes
    to recognize on their own -- see canonical_categories.register_category>}].

    Applies every decision's fields onto its representative row, fans
    the result out to every original code in that (description, unit)
    group (see ingest.dedupe_by_description), then merges the job's
    ENTIRE current row set -- not just the codes touched by this
    particular confirm call -- into the company's own
    master_item_codes.json. This makes repeated partial confirm calls
    against the same job safe: earlier confirmed rows are re-written
    with the same values, not lost, and rows nobody has reviewed yet are
    written as-is (typically still need_review), matching the existing
    convention already visible in Provident's own master file today.
    """
    job = load_job(company_id, job_id)
    if job is None:
        raise ValueError(f"No onboarding job {job_id!r} found for company {company_id!r}.")

    code_groups: dict[str, list[str]] = job["code_groups"]
    rows: dict[str, dict] = job["rows"]

    applied_rep_codes = 0
    applied_member_codes = 0
    new_categories_registered: list[str] = []
    # Loaded once and kept in sync locally as decisions register new
    # categories, so confirming several rows under the SAME brand-new
    # category name in one call (the common case -- a reviewer classifies
    # a handful of different item-code groups as one new material) only
    # registers it once instead of raising on the second attempt.
    known_categories = canonical_categories.load_canonical_categories()

    for decision in decisions:
        rep_code = decision.get("code")
        if rep_code not in rows:
            raise ValueError(f"Decision references code {rep_code!r}, which isn't part of onboarding job {job_id!r}.")

        fields = decision.get("fields") or {}
        register_as = decision.get("register_as_new_category")

        if register_as and register_as not in known_categories:
            canonical_categories.register_category(register_as, dict(fields))
            known_categories[register_as] = dict(fields)
            new_categories_registered.append(register_as)

        if not fields:
            continue

        rows[rep_code].update(fields)
        applied_rep_codes += 1
        applied_member_codes += len(code_groups.get(rep_code, [rep_code]))

    master_path = company_store.master_item_codes_path(company_id)
    master = json.loads(master_path.read_text()) if master_path.exists() else {}
    for rep_code, row in rows.items():
        for member_code in code_groups.get(rep_code, [rep_code]):
            master[member_code] = dict(row)
    master_path.parent.mkdir(parents=True, exist_ok=True)
    master_path.write_text(json.dumps(master, indent=2))

    job["status"] = "confirmed"
    job["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    _save_job(company_id, job)

    return {
        "job_id": job_id,
        "company_id": company_id,
        "decisions_applied": applied_rep_codes,
        "codes_written": applied_member_codes,
        "total_codes_in_master": len(master),
        "master_path": str(master_path),
        "new_categories_registered": new_categories_registered,
    }