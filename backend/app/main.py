"""FastAPI entrypoint for the conceptual carbon calculator backend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import boq_carbon, boq_carbon_substitute, calculate, form, refine, substitute

app = FastAPI(title="Conceptual Carbon Calculator API")

# Required for the frontend (Vite dev server on localhost:5173) to be
# able to call this API at all -- without this middleware, browsers
# block every request with a CORS error before it even reaches these
# routes, regardless of whether the routes themselves are correct.
# Add your production frontend's origin here too once deployed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(form.router)
app.include_router(calculate.router)
app.include_router(substitute.router)
app.include_router(refine.router)
app.include_router(boq_carbon.router)  # Phase 2: raw-BOQ-in, carbon-out -- standalone from the tiered form flow
app.include_router(boq_carbon_substitute.router)  # Phase 2: material substitution, real recompute against the catalog


@app.get("/health")
def health():
    return {"status": "ok"}
