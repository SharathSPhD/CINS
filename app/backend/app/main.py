"""CINS FastAPI app — the backend layer of the kundali architecture
(deterministic engine -> FastAPI -> Next.js/Vercel -> Supabase, docs/PRD.md
§3.2). Run with:

    .venv/bin/uvicorn app.main:app --reload --app-dir app/backend --port 8000

(single worker — the /api/inverse job store in app/jobs.py is in-process and
not safe to shard across multiple uvicorn workers; see app/README.md).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import analyze, fit, health, inverse, presolve

app = FastAPI(
    title="CINS API",
    description=(
        "Deterministic monolithic CST-Newton inverse airfoil design — "
        "FastAPI shell over the cins engine core (docs/PRD.md)."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(fit.router)
app.include_router(presolve.router)
app.include_router(inverse.router)
