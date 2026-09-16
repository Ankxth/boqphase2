"""Calculation endpoint -- runs the full results pipeline (carbon, cost,
GRIHA-style benchmark, GRIHA V6.0 Criterion 21 estimate) for a project
that's already been submitted via POST /form (and optionally edited via
PATCH /form/{project_id}).

Deliberately does NOT re-run BOQ matching or LLM fallback -- those
already ran at form-submission time and any subsequent user edits via
PATCH take priority. This endpoint only computes results from whatever
state the project is currently saved in.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import company_store, project_store
from app.services.calculation_engine import CalculationResult, calculate_embodied_carbon
from app.services.cost_estimation import CostEstimate, estimate_cost
from app.services.benchmark import BenchmarkResult, compute_benchmark
from app.services.griha_criterion21 import GrihaCriterion21Estimate, estimate_criterion_21

router = APIRouter()


class CalculateResponse(BaseModel):
    project_id: str
    carbon: CalculationResult
    cost: CostEstimate
    benchmark: BenchmarkResult
    griha_criterion_21: GrihaCriterion21Estimate


@router.post("/calculate/{project_id}", response_model=CalculateResponse)
def calculate(project_id: str, company_id: str = company_store.DEFAULT_COMPANY_ID) -> CalculateResponse:
    # company_id is for LOOKUP only (Workstream 04) -- estimate_cost()
    # and every other call below reads the loaded project's own
    # company_id field, not this parameter.
    project = project_store.load_project(project_id, company_id=company_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project found with id '{project_id}'")

    if project.mandatory.gfa_sqm.value is None:
        raise HTTPException(status_code=400, detail="Cannot calculate without a valid GFA")

    carbon_result = calculate_embodied_carbon(project)
    cost_result = estimate_cost(project, carbon_result)
    benchmark_result = compute_benchmark(project, carbon_result)
    griha_result = estimate_criterion_21(project, carbon_result)

    return CalculateResponse(
        project_id=project_id,
        carbon=carbon_result,
        cost=cost_result,
        benchmark=benchmark_result,
        griha_criterion_21=griha_result,
    )