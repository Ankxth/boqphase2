"""Workstream 05: generalized TF-IDF similarity triage, from
scripts/similarity_triage.py.

Same discipline as the original script's own docstring: this is a
triage AID, not a classifier. This project's own prior finding is that a
TF-IDF/GloVe/LLM matcher topped out at 58% real classification accuracy
-- not good enough to trust as a standalone classifier. This module does
NOT write to any master dict and does NOT decide anything; it only ranks
each remaining need_review row by cosine similarity to the nearest
already-"yes"-classified row, so a human reviewer sees "these rows look
like plaster" instead of reading a raw need_review list cold.

Generalized from the original script in exactly the same way as
classification_pipeline.py: takes an in-memory master dict instead of a
hardcoded file path, and returns data (a list of dicts) instead of
writing a report file directly -- the caller (app/api/onboarding.py, via
pipeline.py) decides whether/how to render it.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SIMILARITY_FLOOR = 0.15


def rank_similarity(master: dict[str, dict], floor: float = SIMILARITY_FLOOR) -> list[dict]:
    """Returns a list of {code, desc, unit, best_match_code,
    best_match_desc, suggested_category, similarity}, sorted by
    similarity descending, for every need_review row whose best match
    among already-"yes" rows scores at or above `floor`. Rows below the
    floor are omitted entirely (same as the original script) rather than
    shown with a misleadingly confident-looking low match. Returns []
    if there are no "yes" rows to compare against, or no need_review
    rows with text -- both are normal, not errors.
    """
    yes_rows = [(k, v) for k, v in master.items() if (v.get("contributes") or "").strip().lower() == "yes" and v.get("desc")]
    nr_rows = [(k, v) for k, v in master.items() if (v.get("contributes") or "").strip().lower() == "need_review" and v.get("desc")]

    if not yes_rows or not nr_rows:
        return []

    yes_texts = [v["desc"] for _, v in yes_rows]
    nr_texts = [v["desc"] for _, v in nr_rows]

    vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, stop_words="english")
    all_vecs = vectorizer.fit_transform(yes_texts + nr_texts)
    yes_vecs = all_vecs[: len(yes_texts)]
    nr_vecs = all_vecs[len(yes_texts):]

    sims = cosine_similarity(nr_vecs, yes_vecs)  # shape (n_need_review, n_yes)

    results = []
    for i, (code, row) in enumerate(nr_rows):
        best_j = sims[i].argmax()
        best_score = sims[i][best_j]
        if best_score < floor:
            continue
        match_code, match_row = yes_rows[best_j]
        results.append({
            "code": code, "desc": row["desc"], "unit": row.get("unit"),
            "best_match_code": match_code, "best_match_desc": match_row["desc"],
            "suggested_category": match_row.get("material_category"),
            "similarity": round(float(best_score), 3),
        })

    results.sort(key=lambda r: -r["similarity"])
    return results