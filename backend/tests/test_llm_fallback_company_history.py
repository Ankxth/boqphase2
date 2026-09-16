"""Workstream 06: tests for the company-anchored section llm_fallback.py
now adds to its LLM prompt. No network/LLM calls here -- these test the
pure prompt-string builder directly (_build_prompt /
_company_history_section), same as how this file's sibling tests avoid
depending on a configured LLM provider.
"""

from __future__ import annotations

from app.services.llm_fallback import _build_prompt, _company_history_section


def test_no_section_when_history_is_none():
    assert _company_history_section(None) == ""


def test_no_section_when_company_has_zero_reference_projects():
    assert _company_history_section({"n_reference_projects": 0}) == ""


def test_section_included_when_history_has_data():
    history = {
        "n_reference_projects": 2,
        "typology_counts": {"residential": 2},
        "structural_system_type_counts": {"rcc_frame": 2},
        "gfa_sqm_range": {"min": 10000, "max": 20000, "avg": 15000, "n": 2},
        "steel_reinforcement_ratio_kg_per_sqm": {"min": 65.0, "max": 75.0, "avg": 70.0, "n": 2},
        "concrete_vol_per_sqm": {"min": 0.4, "max": 0.45, "avg": 0.425, "n": 2},
    }
    section = _company_history_section(history)
    assert "2 of this company's own past projects" in section
    assert "65.0-75.0" in section
    assert "0.400-0.450" in section
    assert "residential" in section


def test_build_prompt_embeds_company_history_section_when_present():
    prompt = _build_prompt({"mandatory.gfa_sqm": 12000}, ["tier3.steel_reinforcement_ratio_kg_per_sqm"], history={
        "n_reference_projects": 1,
        "typology_counts": {}, "structural_system_type_counts": {},
        "gfa_sqm_range": None,
        "steel_reinforcement_ratio_kg_per_sqm": {"min": 60.0, "max": 60.0, "avg": 60.0, "n": 1},
        "concrete_vol_per_sqm": None,
    })
    assert "This company's own project history" in prompt
    assert "60.0-60.0" in prompt


def test_build_prompt_unchanged_when_no_history_given():
    # Backward compatibility: fill_missing_fields's default call shape
    # (history=None, or a brand-new company's all-zero history) must
    # produce the exact same prompt every caller got before this
    # workstream.
    prompt_no_history = _build_prompt({"mandatory.gfa_sqm": 12000}, ["tier2.num_floors"])
    assert "This company's own project history" not in prompt_no_history