"""CINS FastAPI app — the backend layer of the kundali architecture
(deterministic engine -> FastAPI -> Next.js/Vercel -> Supabase, docs/PRD.md
§3.2). Run with:

    .venv/bin/uvicorn app.main:app --reload --app-dir app/backend --port 8000

(single worker — the /api/inverse job store in app/jobs.py is in-process and
not safe to shard across multiple uvicorn workers; see app/README.md).
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import airfoils, analyze, fit, flowfield, geometry, health, inverse, presolve

app = FastAPI(
    title="CINS API",
    description=(
        "Deterministic monolithic CST-Newton inverse airfoil design — "
        "FastAPI shell over the cins engine core (docs/PRD.md)."
    ),
    version="0.1.0",
)

# ALLOWED_ORIGINS: comma-separated list; defaults to local Next.js dev only.
# Deploy-readiness (app/README.md): set this env var to the deployed frontend
# origin(s) (e.g. the Vercel URL) in production.
_allowed_origins = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(fit.router)
app.include_router(presolve.router)
app.include_router(inverse.router)
app.include_router(airfoils.router)
app.include_router(geometry.router)
app.include_router(flowfield.router)
