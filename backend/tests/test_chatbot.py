"""Workstream 12: tests for app/services/chatbot.py (Phase 3's "what-if"
chatbot) and its endpoints in app/api/phase3.py.

Deliberately exercises the keyword-fallback parser as the PRIMARY tested
path, not an afterthought: this environment has no LLM provider
installed (see llm_fallback.py's own "using placeholder estimates
instead" behavior elsewhere in this suite), so parse_question() always
falls through to _parse_with_keywords() here -- meaning the fallback
parser's correctness is exactly as load-bearing in this test run as it
would be in any environment without groq/ollama configured. The LLM-path
tests below cover it separately via a monkeypatched chat_json().

Every assertion about a savings figure is a real recompute cross-check
against an independently-called calculate_embodied_carbon(), same
discipline test_substitution.py already established -- never a
hardcoded number.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.schemas.project_schema import CementType, FieldValue, ProjectSchema, StructuralSystemType
from app.services import chatbot, company_store, project_store
from app.services.calculation_engine import calculate_embodied_carbon
from app.services.llm_client import LLMUnavailableError

client = TestClient(__import__("app.main", fromlist=["app"]).app)

COMPANY = "provident"


@pytest.fixture(autouse=True)
def isolated_company_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def _project(project_id="chat-proj", cement_type=CementType.opc, grade="M30", steel_ratio=90.0, gfa=40000.0):
    p = ProjectSchema(project_id=project_id, company_id=COMPANY)
    p.mandatory.gfa_sqm = FieldValue(value=gfa, source="user-entered", confidence=1.0)
    p.mandatory.structural_system_type = FieldValue(
        value=StructuralSystemType.rcc_frame, source="user-entered", confidence=1.0
    )
    if cement_type is not None:
        p.tier3.cement_type = FieldValue(value=cement_type, source="user-entered", confidence=1.0)
    if grade is not None:
        p.tier3.concrete_grade_mix = FieldValue(value=grade, source="user-entered", confidence=1.0)
    if steel_ratio is not None:
        p.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(value=steel_ratio, source="user-entered", confidence=1.0)
    return p


# --------------------------------------------------------------------------
# Keyword-fallback parsing -- word-order disambiguation is the load-bearing
# piece here (see module docstring).
# --------------------------------------------------------------------------


def test_parse_instead_of_phrasing_picks_the_first_mention_as_target():
    # The roadmap's own worked example, verbatim.
    call = chatbot._parse_with_keywords("What if I use M40 instead of M30?")
    assert call.tool == "swap_concrete_grade"
    assert call.params["target_grade"] == "M40"


def test_parse_from_x_to_y_phrasing_picks_the_last_mention_as_target():
    call = chatbot._parse_with_keywords("What if I switch from M30 to M40?")
    assert call.tool == "swap_concrete_grade"
    assert call.params["target_grade"] == "M40"


def test_parse_single_grade_mention_is_unambiguous():
    call = chatbot._parse_with_keywords("What if concrete grade were M45?")
    assert call.params["target_grade"] == "M45"


def test_parse_cement_type_instead_of_phrasing():
    call = chatbot._parse_with_keywords("What if I switched to PPC cement instead of OPC?")
    assert call.tool == "swap_cement_type"
    assert call.params["target_cement_type"] == "PPC"


def test_parse_steel_ratio_extracts_number():
    call = chatbot._parse_with_keywords("What if steel reinforcement was 60 kg/sqm?")
    assert call.tool == "swap_steel_ratio"
    assert call.params["target_ratio_kg_per_sqm"] == 60.0


def test_parse_supplier_keyword():
    call = chatbot._parse_with_keywords("What if I used a greener steel supplier?")
    assert call.tool == "swap_steel_supplier"


def test_parse_vague_steel_question_asks_for_a_number():
    call = chatbot._parse_with_keywords("What if we reduce steel a bit?")
    assert call.tool is None
    assert "ratio" in call.clarification.lower()


def test_parse_project_end_question_with_material_verbatim_user_example():
    # The user's own literal example question that prompted this upgrade.
    call = chatbot._parse_with_keywords(
        "give me an estimate of how much carbon only steel would contribute by the end of this project"
    )
    assert call.tool == "get_project_end_estimate"
    assert call.params == {"material": "steel"}


def test_parse_project_end_question_without_material():
    call = chatbot._parse_with_keywords("what will the total carbon be at completion?")
    assert call.tool == "get_project_end_estimate"
    assert call.params == {}


def test_parse_project_end_beats_breakdown_when_both_keywords_present():
    # "contribute" is a _BREAKDOWN_KEYWORDS hit and "by the end" is a
    # _PROJECT_END_KEYWORDS hit in the same sentence -- project-end must
    # win, since that's the actually-asked question (a projection, not
    # today's snapshot).
    call = chatbot._parse_with_keywords("how much carbon would steel contribute by the end of this project?")
    assert call.tool == "get_project_end_estimate"
    assert call.params == {"material": "steel"}


def test_parse_benchmark_question():
    call = chatbot._parse_with_keywords("how does this compare to a typical building?")
    assert call.tool == "get_benchmark_comparison"
    assert call.params == {}


def test_parse_breakdown_question_with_material():
    call = chatbot._parse_with_keywords("how much carbon does steel contribute right now?")
    assert call.tool == "get_carbon_breakdown"
    assert call.params == {"material": "steel"}


def test_parse_breakdown_question_without_material_defaults_to_all():
    call = chatbot._parse_with_keywords("what's my carbon breakdown?")
    assert call.tool == "get_carbon_breakdown"
    assert call.params == {"material": "all"}


def test_parse_totals_question():
    call = chatbot._parse_with_keywords("what's my total carbon and cost so far?")
    assert call.tool == "get_totals"
    assert call.params == {}


def test_parse_bare_material_mention_falls_back_to_breakdown():
    call = chatbot._parse_with_keywords("what about concrete?")
    assert call.tool == "get_carbon_breakdown"
    assert call.params == {"material": "concrete"}


def test_parse_unrelated_question_returns_generic_clarification():
    call = chatbot._parse_with_keywords("What if I painted the building blue?")
    assert call.tool is None
    assert call.clarification == chatbot._GENERIC_CLARIFICATION


# --------------------------------------------------------------------------
# LLM-path parsing (monkeypatched chat_json) -- closed-vocabulary
# enforcement, same discipline as Workstream 05's llm_classifier.
# --------------------------------------------------------------------------


def test_llm_parse_path_used_when_chat_json_succeeds(monkeypatch):
    monkeypatch.setattr(chatbot, "chat_json", lambda prompt: {"tool": "swap_concrete_grade", "params": {"target_grade": "M40"}})
    call = chatbot.parse_question("some question")
    assert call.parse_source == "llm"
    assert call.tool == "swap_concrete_grade"
    assert call.params["target_grade"] == "M40"


def test_llm_inventing_an_unknown_tool_name_is_rejected_to_none(monkeypatch):
    monkeypatch.setattr(chatbot, "chat_json", lambda prompt: {"tool": "delete_the_database", "params": {}})
    call = chatbot.parse_question("some question")
    assert call.tool is None
    assert call.clarification  # falls back to the generic clarification


def test_llm_failure_falls_back_to_keyword_parsing(monkeypatch):
    def _raise(prompt):
        raise LLMUnavailableError("no provider configured")

    monkeypatch.setattr(chatbot, "chat_json", _raise)
    call = chatbot.parse_question("What if I use M40 instead of M30?")
    assert call.parse_source == "keyword_fallback"
    assert call.params["target_grade"] == "M40"


# --------------------------------------------------------------------------
# Execution -- each tool, against a real recompute cross-check
# --------------------------------------------------------------------------


def test_execute_swap_cement_type_matches_independent_recompute():
    project = _project(cement_type=CementType.opc)
    actual = calculate_embodied_carbon(project)

    fields = chatbot._execute_swap_cement_type(project, actual, {"target_cement_type": "PPC"})

    modified = project.model_copy(deep=True)
    modified.tier3.cement_type = FieldValue(value=CementType.ppc, source="user-entered", confidence=1.0)
    expected_after = calculate_embodied_carbon(modified).total_carbon_kg

    assert fields["carbon_kg_after"] == pytest.approx(expected_after)
    assert fields["requires_engineering_review"] is False


def test_execute_swap_cement_type_rejects_unknown_type():
    project = _project()
    actual = calculate_embodied_carbon(project)
    with pytest.raises(ValueError, match="recognized cement type"):
        chatbot._execute_swap_cement_type(project, actual, {"target_cement_type": "XYZ"})


def test_execute_swap_cement_type_already_at_target_is_a_real_no_op():
    project = _project(cement_type=CementType.ppc)
    actual = calculate_embodied_carbon(project)
    fields = chatbot._execute_swap_cement_type(project, actual, {"target_cement_type": "PPC"})
    assert fields["savings_kg"] == 0.0
    assert fields["carbon_kg_after"] == fields["carbon_kg_before"]


def test_execute_swap_concrete_grade_matches_independent_recompute():
    project = _project(grade="M30")
    actual = calculate_embodied_carbon(project)

    fields = chatbot._execute_swap_concrete_grade(project, actual, {"target_grade": "M40"})

    modified = project.model_copy(deep=True)
    modified.tier3.concrete_grade_mix = FieldValue(value="M40", source="user-entered", confidence=1.0)
    expected_after = calculate_embodied_carbon(modified).total_carbon_kg

    assert fields["carbon_kg_after"] == pytest.approx(expected_after)
    # Real, disclosed finding: a HIGHER grade is not automatically lower-carbon.
    assert fields["carbon_kg_after"] != fields["carbon_kg_before"]


def test_execute_swap_concrete_grade_rejects_unrecognized_grade():
    project = _project()
    actual = calculate_embodied_carbon(project)
    with pytest.raises(ValueError, match="recognized concrete grade"):
        chatbot._execute_swap_concrete_grade(project, actual, {"target_grade": "M99"})


def test_execute_swap_steel_ratio_matches_independent_recompute_and_always_flags_review():
    project = _project(steel_ratio=90.0)
    actual = calculate_embodied_carbon(project)

    fields = chatbot._execute_swap_steel_ratio(project, actual, {"target_ratio_kg_per_sqm": 60.0})

    modified = project.model_copy(deep=True)
    modified.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(value=60.0, source="user-entered", confidence=1.0)
    expected_after = calculate_embodied_carbon(modified).total_carbon_kg

    assert fields["carbon_kg_after"] == pytest.approx(expected_after)
    assert fields["requires_engineering_review"] is True


def test_execute_swap_steel_ratio_rejects_non_positive():
    project = _project()
    actual = calculate_embodied_carbon(project)
    with pytest.raises(ValueError, match="positive"):
        chatbot._execute_swap_steel_ratio(project, actual, {"target_ratio_kg_per_sqm": -5})


def test_execute_swap_steel_ratio_rejects_non_numeric():
    project = _project()
    actual = calculate_embodied_carbon(project)
    with pytest.raises(ValueError, match="usable steel ratio"):
        chatbot._execute_swap_steel_ratio(project, actual, {"target_ratio_kg_per_sqm": "a lot"})


def test_execute_swap_steel_supplier_matches_catalog_and_always_flags_review():
    project = _project(steel_ratio=90.0)
    actual = calculate_embodied_carbon(project)
    fields = chatbot._execute_swap_steel_supplier(project, actual, {})
    assert fields["carbon_kg_after"] < fields["carbon_kg_before"]
    assert fields["requires_engineering_review"] is True
    assert "ARS" in fields["suggested_value"] or "kgCO2e/kg" in fields["suggested_value"]


def test_execute_swap_steel_supplier_requires_a_steel_quantity_basis():
    project = _project(steel_ratio=None)
    actual = calculate_embodied_carbon(project)
    with pytest.raises(ValueError, match="no steel quantity basis"):
        chatbot._execute_swap_steel_supplier(project, actual, {})


# --------------------------------------------------------------------------
# Workstream 13: the four read-only "query" tools -- every figure is
# cross-checked against an independent call to the same underlying
# service the executor itself calls (never a hardcoded expected number).
# --------------------------------------------------------------------------


def test_execute_get_carbon_breakdown_all_matches_independent_recompute():
    project = _project(steel_ratio=90.0)
    actual = calculate_embodied_carbon(project)
    fields = chatbot._execute_get_carbon_breakdown(project, actual, {})

    concrete_item = next(b for b in actual.breakdown if b.material.startswith("Concrete"))
    steel_item = next(b for b in actual.breakdown if b.material.startswith("Reinforcement steel"))

    data = fields["data"]
    assert data["total_carbon_kg"] == pytest.approx(actual.total_carbon_kg)
    assert data["concrete_carbon_kg"] == pytest.approx(concrete_item.carbon_kg)
    assert data["steel_carbon_kg"] == pytest.approx(steel_item.carbon_kg)
    assert data["concrete_pct_of_total"] + data["steel_pct_of_total"] == pytest.approx(100.0, abs=0.1)
    assert fields["applied"] is True


def test_execute_get_carbon_breakdown_single_material_only_includes_that_material():
    project = _project()
    actual = calculate_embodied_carbon(project)
    fields = chatbot._execute_get_carbon_breakdown(project, actual, {"material": "steel"})
    data = fields["data"]
    assert "steel_carbon_kg" in data
    assert "concrete_carbon_kg" not in data


def test_execute_get_carbon_breakdown_rejects_invalid_material():
    project = _project()
    actual = calculate_embodied_carbon(project)
    with pytest.raises(ValueError, match="material"):
        chatbot._execute_get_carbon_breakdown(project, actual, {"material": "glass"})


def test_execute_get_totals_matches_independent_recompute():
    from app.services.cost_estimation import estimate_cost

    project = _project()
    actual = calculate_embodied_carbon(project)
    fields = chatbot._execute_get_totals(project, actual, {})
    expected_cost = estimate_cost(project, actual)

    data = fields["data"]
    assert data["total_carbon_kg"] == pytest.approx(actual.total_carbon_kg)
    assert data["carbon_per_sqm"] == pytest.approx(actual.carbon_per_sqm)
    assert data["total_cost_inr"] == pytest.approx(expected_cost.total_cost_inr)
    assert data["cost_per_sqm_inr"] == pytest.approx(expected_cost.cost_per_sqm_inr)


def test_execute_get_benchmark_comparison_matches_independent_compute_benchmark():
    from app.services.benchmark import compute_benchmark

    project = _project()
    actual = calculate_embodied_carbon(project)
    fields = chatbot._execute_get_benchmark_comparison(project, actual, {})
    expected = compute_benchmark(project, actual)

    data = fields["data"]
    assert data["actual_carbon_per_sqm"] == pytest.approx(expected.actual_carbon_per_sqm)
    assert data["typical_carbon_per_sqm"] == pytest.approx(expected.baseline_carbon_per_sqm)
    assert data["comparison_label"] == expected.comparison_label
    assert data["disclaimer"] == expected.disclaimer


def test_execute_get_project_end_estimate_falls_back_to_phase1_live_estimate_when_no_baseline():
    project = _project(project_id="pe-live")
    actual = calculate_embodied_carbon(project)
    fields = chatbot._execute_get_project_end_estimate(project, actual, {})
    data = fields["data"]
    assert data["source"] == "phase1_live_estimate"
    assert data["projected_total_carbon_kg"] == pytest.approx(actual.total_carbon_kg)


def test_execute_get_project_end_estimate_uses_recorded_baseline_when_no_bills_yet():
    from app.services import phase3

    project = _project(project_id="pe-baseline")
    actual = calculate_embodied_carbon(project)
    baseline = phase3.Phase3Baseline(
        project_id="pe-baseline", company_id=COMPANY, source_type="boq", source_file="test.xlsx",
        recorded_at="2026-01-01T00:00:00", total_gwp_kg_co2e=999_000.0, total_value=1_000_000.0,
    )
    phase3.save_baseline(baseline)

    fields = chatbot._execute_get_project_end_estimate(project, actual, {})
    data = fields["data"]
    assert data["source"] == "phase3_baseline_boq"
    assert data["projected_total_carbon_kg"] == pytest.approx(999_000.0)


def test_execute_get_project_end_estimate_uses_billed_projection_when_bills_exist():
    from app.services import phase3

    project = _project(project_id="pe-billed")
    actual = calculate_embodied_carbon(project)
    baseline = phase3.Phase3Baseline(
        project_id="pe-billed", company_id=COMPANY, source_type="boq", source_file="test.xlsx",
        recorded_at="2026-01-01T00:00:00", total_gwp_kg_co2e=1_000_000.0, total_value=2_000_000.0,
    )
    phase3.save_baseline(baseline)
    bill = phase3.BillPeriod(
        project_id="pe-billed", company_id=COMPANY, period="2026-Q1", billed_date="2026-03-31",
        source_file="bill.xlsx", recorded_at="2026-04-01T00:00:00", stated_percent_complete=25.0,
        total_gwp_kg_co2e_to_date=250_000.0, total_value_to_date=500_000.0,
        cost_per_kg_co2e_to_date=2.0, n_lines_computed=10, n_lines_total=10,
    )
    phase3.save_bill_period(bill)

    fields = chatbot._execute_get_project_end_estimate(project, actual, {})
    data = fields["data"]
    assert data["source"] == "billed_projection"
    # 250,000 kgCO2e at 25% complete -> projected total 1,000,000.
    assert data["projected_total_carbon_kg"] == pytest.approx(1_000_000.0)


def test_execute_get_project_end_estimate_material_split_is_phase1_derived():
    project = _project(project_id="pe-split", steel_ratio=90.0)
    actual = calculate_embodied_carbon(project)
    fields = chatbot._execute_get_project_end_estimate(project, actual, {"material": "steel"})
    data = fields["data"]
    assert data["material_split_basis"] == "phase1_concept_estimate"
    steel_item = next(b for b in actual.breakdown if b.material.startswith("Reinforcement steel"))
    expected_share = steel_item.carbon_kg / actual.total_carbon_kg
    assert data["material_share_pct"] == pytest.approx(expected_share * 100, abs=0.01)
    assert data["projected_material_carbon_kg"] == pytest.approx(data["projected_total_carbon_kg"] * expected_share)


def test_execute_get_project_end_estimate_rejects_invalid_material():
    project = _project(project_id="pe-bad-material")
    actual = calculate_embodied_carbon(project)
    with pytest.raises(ValueError, match="material"):
        chatbot._execute_get_project_end_estimate(project, actual, {"material": "glass"})


# --------------------------------------------------------------------------
# answer_question() end to end -- service-level
# --------------------------------------------------------------------------


def test_answer_question_full_success_path():
    project_store.save_project(_project(project_id="p-full", grade="M30"))
    answer = chatbot.answer_question("p-full", COMPANY, "What if I use M40 instead of M30?")
    assert answer.applied is True
    assert answer.tool_call.tool == "swap_concrete_grade"
    assert "M40" in answer.answer_text


def test_answer_question_no_phase1_record():
    answer = chatbot.answer_question("no-such-project", COMPANY, "What if I use M40 instead of M30?")
    assert answer.applied is False
    assert answer.error == "no_phase1_record"


def test_answer_question_no_gfa():
    p = ProjectSchema(project_id="p-no-gfa", company_id=COMPANY)
    project_store.save_project(p)
    answer = chatbot.answer_question("p-no-gfa", COMPANY, "What if I use M40 instead of M30?")
    assert answer.applied is False
    assert answer.error == "no_gfa"


def test_answer_question_unparseable():
    project_store.save_project(_project(project_id="p-unparse"))
    answer = chatbot.answer_question("p-unparse", COMPANY, "What if I painted the building blue?")
    assert answer.applied is False
    assert answer.error == "unparseable_question"


def test_answer_question_invalid_parameter_surfaces_as_error_not_a_crash(monkeypatch):
    # The keyword fallback's own grade regex only ever matches real grades
    # (it's the same closed set _valid_grades() checks), so it can't
    # produce an out-of-range value on its own -- exercising the
    # invalid-parameter path end to end means simulating an LLM response
    # that names a real tool but a bogus parameter, which the executor
    # must still catch and report, not crash on.
    monkeypatch.setattr(
        chatbot, "chat_json", lambda prompt: {"tool": "swap_concrete_grade", "params": {"target_grade": "M99"}}
    )
    project_store.save_project(_project(project_id="p-bad-grade"))
    answer = chatbot.answer_question("p-bad-grade", COMPANY, "What if concrete grade were M99?")
    assert answer.applied is False
    assert answer.error == "invalid_parameters"


def test_answer_question_project_end_estimate_verbatim_user_example():
    project_store.save_project(_project(project_id="p-end-estimate", steel_ratio=90.0))
    answer = chatbot.answer_question(
        "p-end-estimate", COMPANY,
        "give me an estimate of how much carbon only steel would contribute by the end of this project",
    )
    assert answer.applied is True
    assert answer.tool_call.tool == "get_project_end_estimate"
    assert answer.data["material"] == "steel"
    assert answer.data["source"] == "phase1_live_estimate"
    # Backward-compat: swap-only fields stay None for a query tool.
    assert answer.current_value is None
    assert answer.carbon_kg_before is None


def test_answer_question_carbon_breakdown():
    project_store.save_project(_project(project_id="p-breakdown"))
    answer = chatbot.answer_question("p-breakdown", COMPANY, "how much carbon does steel contribute?")
    assert answer.applied is True
    assert answer.tool_call.tool == "get_carbon_breakdown"
    assert "steel_carbon_kg" in answer.data


def test_answer_question_totals():
    project_store.save_project(_project(project_id="p-totals"))
    answer = chatbot.answer_question("p-totals", COMPANY, "what's my total carbon and cost so far?")
    assert answer.applied is True
    assert answer.tool_call.tool == "get_totals"
    assert answer.data["total_carbon_kg"] > 0


def test_answer_question_benchmark_comparison():
    project_store.save_project(_project(project_id="p-benchmark"))
    answer = chatbot.answer_question("p-benchmark", COMPANY, "how does this compare to a typical building?")
    assert answer.applied is True
    assert answer.tool_call.tool == "get_benchmark_comparison"
    assert answer.data["comparison_label"] in ("above typical", "at typical", "below typical")


def test_answer_question_query_tool_invalid_material_surfaces_as_error(monkeypatch):
    monkeypatch.setattr(
        chatbot, "chat_json", lambda prompt: {"tool": "get_carbon_breakdown", "params": {"material": "glass"}}
    )
    project_store.save_project(_project(project_id="p-bad-material"))
    answer = chatbot.answer_question("p-bad-material", COMPANY, "how much carbon does glass contribute?")
    assert answer.applied is False
    assert answer.error == "invalid_parameters"


# --------------------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------------------


def test_chat_tools_endpoint_lists_all_eight_tools():
    r = client.get("/phase3/chat/tools")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "swap_cement_type", "swap_concrete_grade", "swap_steel_ratio", "swap_steel_supplier",
        "get_carbon_breakdown", "get_totals", "get_benchmark_comparison", "get_project_end_estimate",
    }
    swap_kinds = {name: entry["kind"] for name, entry in body.items() if name.startswith("swap_")}
    assert all(kind == "swap" for kind in swap_kinds.values())
    query_kinds = {name: entry["kind"] for name, entry in body.items() if name.startswith("get_")}
    assert all(kind == "query" for kind in query_kinds.values())


def test_chat_endpoint_full_flow():
    r_form = client.post(
        "/form",
        json={
            "project_name": "API Chat Tower", "gfa_sqm": 30000, "location": "Chennai",
            "structural_system_type": "rcc_frame", "cement_type": "OPC", "concrete_grade_mix": "M30",
            "company_id": COMPANY,
        },
    )
    pid = r_form.json()["project_id"]

    r = client.post(f"/phase3/projects/{pid}/chat", json={"question": "What if I use M40 instead of M30?"}, params={"company_id": COMPANY})
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert body["tool_call"]["params"]["target_grade"] == "M40"


def test_chat_endpoint_always_returns_200_even_for_unanswerable_questions():
    r_form = client.post("/form", json={"gfa_sqm": 30000, "location": "Chennai", "structural_system_type": "rcc_frame", "company_id": COMPANY})
    pid = r_form.json()["project_id"]

    r = client.post(f"/phase3/projects/{pid}/chat", json={"question": "What if I painted it blue?"}, params={"company_id": COMPANY})
    assert r.status_code == 200
    assert r.json()["applied"] is False


def test_chat_endpoint_200_for_nonexistent_project_with_explanatory_answer():
    r = client.post("/phase3/projects/no-such-project/chat", json={"question": "What if I use M40 instead of M30?"}, params={"company_id": COMPANY})
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is False
    assert body["error"] == "no_phase1_record"


def test_chat_endpoint_answers_a_general_carbon_and_cost_question():
    # End-to-end coverage of the user's own request: "can we upgrade this
    # chatbot to answer any questions related to a project and their
    # carbon and cost" -- exercised here via the real HTTP endpoint, not
    # just the service function.
    r_form = client.post(
        "/form",
        json={
            "project_name": "Query Tower", "gfa_sqm": 40000, "location": "Bengaluru",
            "structural_system_type": "rcc_frame", "cement_type": "OPC", "concrete_grade_mix": "M30",
            "steel_reinforcement_ratio_kg_per_sqm": 85, "company_id": COMPANY,
        },
    )
    pid = r_form.json()["project_id"]

    r = client.post(
        f"/phase3/projects/{pid}/chat",
        json={"question": "give me an estimate of how much carbon only steel would contribute by the end of this project"},
        params={"company_id": COMPANY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert body["tool_call"]["tool"] == "get_project_end_estimate"
    assert body["data"]["material"] == "steel"
    assert body["data"]["source"] == "phase1_live_estimate"