"""LLM-based inflation/price-correction adjustment for BOQ-sourced cost
rates.

A raw BOQ rate is a HISTORICAL price from whenever that BOQ was priced --
cost_estimation.py flags this, but doesn't correct it. This module
attempts a correction, using Groq/Ollama (via llm_client.py) to estimate
the approximate cumulative cost increase for each material category
between the BOQ's pricing year and the current year.

Materials sharing the same pricing year are adjusted in ONE batched LLM
call, not one call per material. This matters: two independent calls
have no visibility into each other's answer, and testing showed this
produces a real failure mode -- concrete and steel both landed on
exactly the same 35.0% figure in separate calls, despite citing
different reasoning (cement/fuel prices vs. raw-material/demand), which
is a strong sign the model was reaching for a generic "construction
costs rose ~35%" heuristic rather than reasoning about each material's
actual distinct market drivers (cement/aggregate pricing and iron-ore/
scrap-steel pricing don't historically move in lockstep). A single
batched call, explicitly asked to compare and justify any convergence,
structurally prevents this -- the model has to account for both
materials in one coherent answer rather than reaching for the same
default twice.

This is fundamentally an LLM ESTIMATE of inflation trends, not real
market index data. The raw BOQ rate, the multiplier applied, and the
LLM's own stated reasoning are always returned together.

Requires knowing the BOQ's pricing year. If unknown, NO adjustment is
applied and the raw historical rate is used as-is.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.services.llm_client import LLMUnavailableError, chat_json

MIN_CUMULATIVE_PCT = 0.0
MAX_CUMULATIVE_PCT = 300.0


class InflationAdjustment(BaseModel):
    multiplier: float
    priced_year: Optional[int]
    current_year: int
    cumulative_pct_increase: float
    reasoning: str
    applied: bool


def _current_year() -> int:
    return datetime.now().year


def _build_batch_prompt(materials: list[str], priced_year: int, current_year: int) -> str:
    materials_json = json.dumps(materials)
    return f"""Estimate the approximate cumulative percentage increase in Indian
construction material costs from {priced_year} to {current_year}, for
EACH of the following material categories separately:
{materials_json}

IMPORTANT: These material categories have historically DIFFERENT price
drivers and often do NOT move at the same rate:
- Cement/concrete pricing is driven by factors like coal/pet-coke fuel
  costs, limestone/clinker availability, freight, and regional cement
  industry capacity.
- Steel/reinforcement pricing is driven by factors like international
  iron ore prices, scrap steel markets, energy costs for steel
  production, and trade policy (tariffs, anti-dumping duties).

Reason about each material's OWN specific drivers over this period. Do
NOT default to the same generic "construction costs rose by X%" figure
for every material unless you have a specific reason both categories
moved identically -- if your estimates do come out similar, briefly
justify why in the reasoning, rather than it being a coincidence of
reaching for a round number.

Respond with ONLY a JSON object, no explanation outside it, no markdown:
{{"materials": {{"<material name exactly as given>": {{"cumulative_pct_increase": <number>, "reasoning": "<one or two sentences specific to this material's own drivers>"}}, ...}}}}"""


def get_inflation_adjustments(materials: list[str], priced_year: Optional[int]) -> dict[str, InflationAdjustment]:
    """Returns an InflationAdjustment per material, from ONE batched LLM
    call covering all of them together (see module docstring for why
    batching matters). If priced_year is None, or the LLM call fails,
    every material gets a no-op adjustment with a clear reason.
    """
    current_year = _current_year()

    if priced_year is None:
        return {
            m: InflationAdjustment(
                multiplier=1.0,
                priced_year=None,
                current_year=current_year,
                cumulative_pct_increase=0.0,
                reasoning="Pricing year unknown for this BOQ -- no inflation adjustment applied. Rate is the raw historical BOQ rate.",
                applied=False,
            )
            for m in materials
        }

    if priced_year >= current_year:
        return {
            m: InflationAdjustment(
                multiplier=1.0,
                priced_year=priced_year,
                current_year=current_year,
                cumulative_pct_increase=0.0,
                reasoning=f"BOQ priced in {priced_year}, not before {current_year} -- no adjustment needed.",
                applied=False,
            )
            for m in materials
        }

    prompt = _build_batch_prompt(materials, priced_year, current_year)
    try:
        parsed = chat_json(prompt)
        material_results = parsed["materials"]
    except (LLMUnavailableError, Exception) as e:
        return {
            m: InflationAdjustment(
                multiplier=1.0,
                priced_year=priced_year,
                current_year=current_year,
                cumulative_pct_increase=0.0,
                reasoning=f"LLM call failed ({e}) -- no adjustment applied, raw historical rate used.",
                applied=False,
            )
            for m in materials
        }

    adjustments: dict[str, InflationAdjustment] = {}
    for material in materials:
        entry = material_results.get(material)
        if entry is None:
            adjustments[material] = InflationAdjustment(
                multiplier=1.0,
                priced_year=priced_year,
                current_year=current_year,
                cumulative_pct_increase=0.0,
                reasoning=f"LLM response did not include an estimate for '{material}' -- no adjustment applied.",
                applied=False,
            )
            continue

        try:
            pct = float(entry["cumulative_pct_increase"])
            reasoning = str(entry.get("reasoning", "")).strip()
        except (KeyError, ValueError, TypeError):
            adjustments[material] = InflationAdjustment(
                multiplier=1.0,
                priced_year=priced_year,
                current_year=current_year,
                cumulative_pct_increase=0.0,
                reasoning=f"LLM response for '{material}' was malformed -- no adjustment applied.",
                applied=False,
            )
            continue

        clamped_pct = max(MIN_CUMULATIVE_PCT, min(pct, MAX_CUMULATIVE_PCT))
        if clamped_pct != pct:
            reasoning += f" [Clamped from {pct}% to {clamped_pct}% -- outside plausible range.]"

        adjustments[material] = InflationAdjustment(
            multiplier=1 + (clamped_pct / 100),
            priced_year=priced_year,
            current_year=current_year,
            cumulative_pct_increase=clamped_pct,
            reasoning=reasoning or "No reasoning provided by the model.",
            applied=True,
        )

    return adjustments