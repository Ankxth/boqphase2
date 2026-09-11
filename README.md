# Conceptual carbon calculator

Tier-based (Mandatory / Tier 2 / Tier 3) input tool that estimates embodied
carbon, GHG, and cost for a building at the conceptual stage, benchmarks it
against a self-computed reference building, and suggests material
substitutions with live recompute.

This is a standalone feature, separate from the other BOQ carbon projects.

## Structure

- `backend/` — FastAPI service: tiered form intake, BOQ-match/LLM fallback,
  ICE + CEA-adjusted calculation engine, benchmarking, substitution recompute.
- `frontend/` — Next.js app: tiered form, editable review step, results dashboard.
- `docs/methodology.md` — pinned decisions on the ICE→CEA adjustment and the
  GRIHA-style baseline benchmark.

## Setup

```bash
# backend
cd backend
python -m venv venv
source venv/Scripts/activate   # Git Bash on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm run dev
```

Place your ICE v4.1 files in `backend/app/data/ice_db/`, CEA baseline data in
`backend/app/data/cea_baseline/`, and reference BOQs (Botanico, Ecopolitan) in
`backend/app/data/reference_boqs/`.
# boqupload
