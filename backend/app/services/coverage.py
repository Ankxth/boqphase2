"""Workstream 07: shared coverage / honesty-reporting layer for both
carbon engines (boq_carbon and wo_carbon).

Both engines have always tracked "how much of this document did we
actually compute" informally -- n_lines_total vs n_lines_computed,
total_wo_amount vs computed_wo_amount -- but nothing turned that into a
structured, user-facing answer to "what got left out, and why", and
nothing singled out the ~5 material categories (concrete, reinforcement
steel, structural steel, aluminium, glass) that this project's own
user-facing copy already calls out as the ones "we verify... to
primary-source rigor" -- see the roadmap's "top5" framing. wo_carbon's
master item-code dataset has carried a per-row `top5` flag since it was
first built, but nothing ever read it; this module is what finally does.

Design, deliberately shared rather than duplicated per engine:

- TOP5_MATERIAL_CATEGORIES is the one place the "top 5" set is defined.
  wo_carbon_engine.py additionally has a real, human-curated per-Activity-
  Code `top5` flag on its master file and reads that directly (more
  faithful to the curated dataset than recomputing); boq_carbon has no
  such per-row flag (it classifies from raw regex, not a curated lookup),
  so it tests category membership in this same set instead -- same
  underlying concept, the only version reachable without a human-curated
  flag of its own. See each engine's own coverage-building helper.

- A FIXED six-reason exclusion taxonomy, so a result's coverage summary
  is finite and scannable rather than a wall of unique basis_note
  strings (some of which -- e.g. wo_carbon's "'{category}' has no
  computation branch yet" -- are deliberately specific and stay exactly
  as they are on the line item itself; this module only buckets them for
  the summary). Not every engine produces every reason (boq_carbon has
  no contributes-flag concept, so it never emits NOT_CONTRIBUTING or
  NEEDS_REVIEW; wo_carbon's PDF parser always yields a real qty, so it
  never emits NO_QUANTITY) -- that's expected, not a bug.
"""

from __future__ import annotations

from pydantic import BaseModel

# The ~5 material categories that drive most of a typical building's
# embodied carbon -- concrete, reinforcement steel, structural steel
# (rolled sections), aluminium, glass. Deliberately does NOT include
# timber_wood/steel_gi_galvanized even though a handful of rows in the
# real Provident master dataset carry top5="yes" for those too (13 and 1
# rows respectively, out of 631 top5 rows total) -- those look like
# project-specific human judgment calls on a handful of high-value rows,
# not a claim that timber/GI-steel belong in the general "big 5" set this
# module's own category-membership fallback (for boq_carbon, which has no
# per-row human-curated flag) needs to reproduce consistently across any
# project, not just Provident's.
TOP5_MATERIAL_CATEGORIES = frozenset({
    "concrete", "reinforcement_steel", "structural_steel", "aluminium", "glass",
})

# Fixed six-reason exclusion taxonomy.
REASON_UNCLASSIFIED = "unclassified"  # classifier/master lookup found no material category at all
REASON_NOT_CONTRIBUTING = "not_contributing"  # explicitly flagged non-material (service/labour/admin/land)
REASON_NEEDS_REVIEW = "needs_review"  # classification pending / ambiguous, not yet confirmed either way
REASON_NO_EMISSION_FACTOR = "no_emission_factor"  # category recognized, but no canonical EF exists for it
REASON_UNHANDLED_UNIT = "unhandled_unit"  # category + EF both exist, but this row's unit/shape has no conversion formula yet
REASON_NO_QUANTITY = "no_quantity"  # no usable quantity or unit on the row at all

ALL_REASONS = [
    REASON_UNCLASSIFIED,
    REASON_NOT_CONTRIBUTING,
    REASON_NEEDS_REVIEW,
    REASON_NO_EMISSION_FACTOR,
    REASON_UNHANDLED_UNIT,
    REASON_NO_QUANTITY,
]


class CoverageExclusion(BaseModel):
    reason: str
    line_item_count: int
    value_excluded: float


class Coverage(BaseModel):
    total_value: float
    computed_value: float
    coverage_pct: float
    # The same two figures, restricted to top5-category line items only --
    # this is the number that matters most for the "we verify the ~5
    # materials that drive most of a building's embodied carbon to
    # primary-source rigor" claim; overall coverage_pct can look fine
    # while the actually-important top5 slice still has real gaps.
    top5_total_value: float
    top5_computed_value: float
    top5_coverage_pct: float
    excluded_by_reason: list[CoverageExclusion]


def _pct(numerator: float, denominator: float) -> float:
    return (numerator / denominator * 100.0) if denominator else 0.0


def build_coverage(rows: list[dict]) -> Coverage:
    """rows: one dict per line item, already reduced to exactly the four
    fields this function needs -- {"value": float, "computed": bool,
    "is_top5": bool, "reason": Optional[str]} -- so this stays engine-
    agnostic. `reason` is ignored (and may be None) for any row where
    computed is True. Both engines build this list from their own richer
    LineItemResult/WoLineItemResult objects via a small per-engine helper
    -- see calculate_from_boq()'s and calculate_from_work_order()'s own
    coverage-building step.
    """
    total_value = sum(r["value"] for r in rows)
    computed_value = sum(r["value"] for r in rows if r["computed"])

    top5_rows = [r for r in rows if r["is_top5"]]
    top5_total_value = sum(r["value"] for r in top5_rows)
    top5_computed_value = sum(r["value"] for r in top5_rows if r["computed"])

    by_reason: dict[str, dict] = {}
    for r in rows:
        if r["computed"]:
            continue
        reason = r.get("reason") or REASON_UNCLASSIFIED
        bucket = by_reason.setdefault(reason, {"count": 0, "value": 0.0})
        bucket["count"] += 1
        bucket["value"] += r["value"]

    excluded_by_reason = [
        CoverageExclusion(reason=reason, line_item_count=b["count"], value_excluded=b["value"])
        for reason, b in sorted(by_reason.items(), key=lambda kv: -kv[1]["value"])
    ]

    return Coverage(
        total_value=total_value,
        computed_value=computed_value,
        coverage_pct=_pct(computed_value, total_value),
        top5_total_value=top5_total_value,
        top5_computed_value=top5_computed_value,
        top5_coverage_pct=_pct(top5_computed_value, top5_total_value),
        excluded_by_reason=excluded_by_reason,
    )