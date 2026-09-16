"""Phase 2: full-BOQ embodied carbon estimation.

Separate from the tiered conceptual estimator (app/schemas/project_schema.py,
app/services/boq_match.py, calculation_engine.py, etc. -- "Phase 1"). This
subpackage takes a real, arbitrary-format BOQ file directly and computes
embodied carbon from actual line-item quantities, rather than scaling a
generic per-sqm ratio.

Modules:
- parser.py     -- format-agnostic hierarchy-aware BOQ extractor. Detects
                    Item No./Description/UOM/Qty/Rate/Amount columns by
                    header TEXT rather than fixed position, so it handles
                    structurally different BOQ layouts without per-file
                    configuration. Confirmed working against 5 real BOQs
                    with 5 different column layouts.
- classifier.py -- keyword/regex material classifier. Sorts each BOQ line
                    into one of ~10 carbon-relevant categories (concrete,
                    reinforcement steel, structural steel, brickwork,
                    blockwork, plaster, tile, paint, aluminium/glazing,
                    glass), and for concrete specifically extracts cement
                    type and grade. Deliberately NOT full SAP-item-code
                    matching -- that was measured (via LLM-judge audit) at
                    only ~58% real accuracy even after reranking, and
                    carbon calculation doesn't need an exact code, only
                    material + grade + quantity.
- extra_factors.py -- DEPRECATED as of Workstream 01 (one emission-factor
                    source). Kept on disk only as a backward-compatible
                    shim and a historical record of the original
                    placeholder-quality numbers' full sourcing writeups.
                    No longer read by engine.py -- see
                    app.services.emission_factors instead.
- engine.py     -- ties parser + classifier + factors together into one
                    calculate_from_boq() entry point. Reuses
                    app.services.ice_factors and app.services.cea_adjustment
                    for concrete/steel, and app.services.emission_factors
                    for every other category -- the same single factor
                    source app.services.wo_carbon.wo_carbon_engine reads
                    too, as of Workstream 01. See
                    docs/workstream01_reconciliation_log.md for what
                    changed when the two pipelines' factors were merged.

Floor area handling: calculate_from_boq() requires an explicit
floor_area_basis alongside floor_area_sqm (e.g. "built_up_total" vs.
"net_internal_gia"). This is not optional decoration -- cross-checking this
pipeline's real BOQ-derived totals against real EDGE certification reports
showed the single largest source of a "wrong" per-sqm number was dividing
by the wrong area definition (an 8.5x gap on one real project), not a
factor-accuracy problem. Every result explicitly states which basis was
used, so a number is never presented without knowing what it was divided
by.
"""