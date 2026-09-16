"""TF-IDF similarity triage, per the project's point-4 instruction: use
embedding similarity as a triage AID, not a classifier.

This project's own prior finding (from an earlier phase) is that a TF-IDF/
GloVe/LLM matcher topped out at 58% real classification accuracy -- not
good enough to trust as a standalone classifier. This script does NOT
classify anything and does NOT write to the master JSON. It only ranks
each remaining `need_review` row by cosine similarity to the nearest
already-`yes`-classified rows, so a human reviewer sees "these 40
unclassified rows look like plaster" instead of reading thousands of rows
cold -- assistive, not authoritative, exactly as instructed.

Usage:
    python similarity_triage.py <master.json> [top_n_clusters]

Writes similarity_triage_report.md: for each need_review row, its single
closest yes-classified row, the cosine similarity score, and that row's
material_category as the suggested-but-NOT-applied category. Rows below a
similarity floor (0.15) are omitted from the report entirely rather than
shown with a misleadingly confident-looking low match.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SIMILARITY_FLOOR = 0.15


def main():
    master_path = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/phase2b/master_item_code_factors_enhanced.json"
    master = json.load(open(master_path))

    yes_rows = [(k, v) for k, v in master.items() if (v.get("contributes") or "").strip().lower() == "yes" and v.get("desc")]
    nr_rows = [(k, v) for k, v in master.items() if (v.get("contributes") or "").strip().lower() == "need_review" and v.get("desc")]

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
        if best_score < SIMILARITY_FLOOR:
            continue
        match_code, match_row = yes_rows[best_j]
        results.append({
            "code": code, "desc": row["desc"], "unit": row.get("unit"),
            "best_match_code": match_code, "best_match_desc": match_row["desc"],
            "suggested_category": match_row.get("material_category"),
            "similarity": round(float(best_score), 3),
        })

    results.sort(key=lambda r: -r["similarity"])

    out_path = Path("/home/claude/phase2b/similarity_triage_report.md")
    lines = [
        "# Similarity triage report (assistive only -- NOT applied to any classification)\n",
        f"{len(nr_rows)} need_review rows with text; {len(results)} matched an already-'yes' row above the {SIMILARITY_FLOOR} cosine-similarity floor ({len(nr_rows) - len(results)} had no close match at all and are not listed).\n",
        "This is a ranking aid only. This project's own prior benchmark found a TF-IDF/GloVe/LLM matcher topped out at 58% real accuracy -- treat every row below as 'worth a human look', never as a decided classification. No `contributes` or `material_category` field was changed by this script.\n",
        "| need_review code | description | closest yes-row | suggested category | similarity |",
        "|---|---|---|---|---|",
    ]
    for r in results[:300]:
        lines.append(f"| {r['code']} | {r['desc'][:60]} | {r['best_match_desc'][:50]} | {r['suggested_category']} | {r['similarity']} |")

    out_path.write_text("\n".join(lines))
    print(f"{len(results)} rows matched above floor {SIMILARITY_FLOOR}, out of {len(nr_rows)} need_review rows with text.")
    print(f"Report written to {out_path}")

    # quick console summary: how many suggest each category
    from collections import Counter
    cat_counts = Counter(r["suggested_category"] for r in results)
    print("\nTop suggested categories (by count of need_review rows pointing at them):")
    for cat, n in cat_counts.most_common(15):
        print(f"  {cat}: {n}")


if __name__ == "__main__":
    main()
