"""Workstream 05: LLM-drafted material-category suggestions for the item
rows classification_pipeline.py's regex/dimension-mining pass could not
resolve -- the "LLM draft only for the remainder" stage of the
onboarding pipeline design.

Calls through app.services.llm_client, the same shared provider
abstraction llm_fallback.py (Phase 1 tier-field estimation) and
boq_extractor.py (ambiguous-row resolution) already use.

This is deliberately STRICTER than llm_fallback.py's discipline, because
a wrong category here writes a wrong emission factor into a company's
permanent item-code dataset, not a soft conceptual-tier estimate that
substitution.py can later recompute away. Two hard constraints, both
enforced in code after the LLM responds, not just requested in the
prompt:

  1. Closed vocabulary -- the LLM is constrained to choosing ONLY from
     the canonical category keys already registered in
     canonical_categories.py (or "none"). It is never invited to invent
     a new category name on its own; a response naming anything outside
     that list is dropped.

  2. Cited evidence -- the LLM must quote the exact word(s) from the
     item's OWN description that justify its answer. A response whose
     cited words don't actually appear in that row's description
     (case-insensitive substring check) is dropped and the row is left
     need_review, on the theory that an LLM that can't even quote real
     text from the row it's looking at is not looking at the row.

Every draft produced here is a SUGGESTION only -- nothing in this module
writes to a master dict or a master_item_codes.json file. A human
reviewer must confirm it via app/api/onboarding.py's /confirm endpoint
(see pipeline.py) before it's applied, same as similarity_triage.py's
suggestions were always assistive-only, never authoritative.

On any LLM failure (unavailable provider, malformed response, etc.) this
module does NOT fall back to a placeholder category the way
llm_fallback.py falls back to a placeholder tier-field value -- guessing
a fake material category with zero real signal would be actively wrong,
not just low-confidence. The affected rows simply get no draft and stay
need_review with no suggestion, which is what the honest default already
looks like.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.services.llm_client import LLMUnavailableError, chat_json

BATCH_SIZE = 40


@dataclass
class LlmDraft:
    code: str
    suggested_category: str
    cited_words: list[str] = field(default_factory=list)
    rationale: str = ""


def _build_prompt(batch: dict[str, dict], canonical_keys: list[str]) -> str:
    items = [{"code": code, "desc": row.get("desc") or "", "unit": row.get("unit") or ""} for code, row in batch.items()]
    return f"""You are helping classify construction Bill-of-Quantities / Work Order
line items into material categories for an embodied-carbon calculator.

Valid categories -- choose ONLY from this exact list, or "none" if
nothing genuinely fits (do not force a match; a wrong category is worse
than no answer):
{json.dumps(canonical_keys)}

Items to classify:
{json.dumps(items, indent=2)}

For each item, respond with the category AND the exact word or words
from THAT ITEM's OWN description that justify your answer -- copy them
verbatim from the description text, do not paraphrase or summarize. If
you cannot point to real words in the description that justify a
category, use "none" and an empty cited_words list rather than guessing.

Respond with ONLY a JSON object of this exact shape (no explanation, no
markdown fences):
{{
  "<code>": {{"category": "<one of the valid categories, or \\"none\\">", "cited_words": ["<word or short phrase copied from the item's own description>"], "rationale": "<one short sentence>"}},
  ...
}}"""


def draft_categories(rows: dict[str, dict], canonical_keys: list[str], batch_size: int = BATCH_SIZE) -> dict[str, LlmDraft]:
    """rows: code -> row dict (desc/unit at minimum) for rows still
    need_review after the regex pass. canonical_keys: the current
    canonical_categories registry's keys. Returns code -> LlmDraft for
    every row that got a verified, defensible suggestion -- rows with no
    draft simply aren't in the returned dict (not an error).
    """
    if not rows or not canonical_keys:
        return {}

    drafts: dict[str, LlmDraft] = {}
    codes = list(rows.keys())

    for i in range(0, len(codes), batch_size):
        batch_codes = codes[i : i + batch_size]
        batch = {c: rows[c] for c in batch_codes}
        prompt = _build_prompt(batch, canonical_keys)

        try:
            raw = chat_json(prompt)
        except (LLMUnavailableError, Exception) as e:
            print(f"[onboarding.llm_classifier] LLM call failed for batch starting {batch_codes[0]!r} ({e}); leaving this batch need_review, no drafts.")
            continue

        if not isinstance(raw, dict):
            print(f"[onboarding.llm_classifier] LLM response for batch starting {batch_codes[0]!r} was not a JSON object; skipping.")
            continue

        for code, entry in raw.items():
            if code not in batch or not isinstance(entry, dict):
                continue

            category = str(entry.get("category", "none")).strip()
            if category.lower() == "none" or category not in canonical_keys:
                continue

            desc_lower = (batch[code].get("desc") or "").lower()
            cited_raw = entry.get("cited_words") or []
            if not isinstance(cited_raw, list):
                cited_raw = [cited_raw]
            valid_cited = [w for w in cited_raw if isinstance(w, str) and w.strip() and w.strip().lower() in desc_lower]

            if not valid_cited:
                print(f"[onboarding.llm_classifier] Dropping draft for {code!r}: cited word(s) {cited_raw!r} not found in its own description {batch[code].get('desc')!r} -- not trusted.")
                continue

            drafts[code] = LlmDraft(
                code=code,
                suggested_category=category,
                cited_words=valid_cited,
                rationale=str(entry.get("rationale", "")),
            )

    return drafts