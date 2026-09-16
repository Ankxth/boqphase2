"""Workstream 05: item-code & Work-Order onboarding pipeline.

Generalizes the five classification-enhancement scripts that were built
and run once, by hand, against Provident's own Ecopolitan dataset
(originally scripts/abbreviation_dictionary.py, dimension_miner.py,
enhance_master_classification.py, similarity_triage.py,
standard_weight_tables.py) into a repeatable, per-company,
endpoint-driven flow any company can run against its own raw item-code
export.

Module map:
  abbreviation_dictionary.py  -- reviewed abbreviation/typo/admin-prefix
                                  normalization layer (moved verbatim
                                  from scripts/, no hardcoded paths to
                                  begin with).
  dimension_miner.py           -- embedded-dimension mass inference for
                                  NOS/EA-priced rows (moved verbatim).
  standard_weight_tables.py    -- IS 808/1239/4985 published weight
                                  tables for steel sections and GI/uPVC
                                  pipe (moved verbatim; still flagged-
                                  not-auto-applied pending MEP scope,
                                  same as the original script).
  canonical_categories.py      -- the cross-company material-category
                                  taxonomy (NEW): the six category
                                  templates the original script had
                                  hardcoded as Python constants, now a
                                  loadable/growable registry shared by
                                  every company.
  classification_pipeline.py   -- the generalized Steps A-E from
                                  enhance_master_classification.py, as a
                                  pure function over an in-memory master
                                  dict (NEW: no hardcoded document paths,
                                  no single-company assumption).
  similarity_triage.py         -- generalized TF-IDF triage (NEW: pure
                                  function, returns data instead of
                                  writing a report file).
  llm_classifier.py            -- NEW: LLM-drafted category suggestions
                                  for rows the regex pass can't resolve,
                                  constrained to the canonical category
                                  list and required to cite the words in
                                  the row's own description that justify
                                  the answer.
  ingest.py                    -- NEW: parses an uploaded raw item-code
                                  workbook and deduplicates it to one row
                                  per unique (description, unit) pair.
  pipeline.py                  -- NEW: top-level orchestration + the
                                  onboarding-job persistence that ties
                                  every stage above together, called by
                                  app/api/onboarding.py.

What this workstream deliberately does NOT do: it does not change how
any of these six steps individually reasons about a description (Steps
A-E's regexes and templates are carried over unchanged from the
Ecopolitan-tested original) -- the generalization is entirely about
*where data comes from and where results go* (in-memory / per-company /
human-reviewed-before-write), not about *how classification decisions
are made*.
"""