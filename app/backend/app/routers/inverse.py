from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app import engine, jobs
from app.schemas import (
    InverseJobResponse,
    InverseRequest,
    InverseSubmitResponse,
    RawTargetGate,
    RawTargetInverseRequest,
    RawTargetSubmitResponse,
)

router = APIRouter(prefix="/api", tags=["inverse"])


@router.post("/inverse", response_model=InverseSubmitResponse, status_code=202)
def submit_inverse(req: InverseRequest, background_tasks: BackgroundTasks) -> dict:
    """Submits a monolithic CST-Newton inverse solve and returns immediately
    with a job_id (NFR-2-style non-blocking; long-running work happens in a
    FastAPI BackgroundTask). Poll GET /api/inverse/{job_id} for status/result.
    At most one solve actually runs at a time (see app.engine.MFOIL_LOCK)."""
    try:
        cfg = engine.build_inverse_config(req)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid inverse config: {exc}") from exc

    job = jobs.create_job()
    background_tasks.add_task(jobs.run_job, job.id, engine.run_inverse, cfg)
    return {"job_id": job.id, "status": job.status}


@router.get("/inverse/{job_id}", response_model=InverseJobResponse)
def poll_inverse(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id {job_id!r}")
    return {
        "job_id": job.id,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "phase": job.phase,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "elapsed_s": time.time() - job.created_at,
        "timeout_s": job.timeout_s,
    }


@router.post("/inverse/gate", response_model=RawTargetGate)
def presolve_gate_raw(req: RawTargetInverseRequest) -> dict:
    """The T4 presolve realisability verdict ONLY (no Newton solve) for a
    user-defined target — lets the UI show the ADR-0004 warning immediately,
    before the user commits to a (slower) full inverse run. Always 200; a
    non-realisable target is a warning, not an error."""
    try:
        return engine.run_presolve_gate_raw(req)["gate"]
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"presolve gate failed: {type(exc).__name__}: {exc}"
        ) from exc


@router.post("/inverse/raw", response_model=RawTargetSubmitResponse, status_code=202)
def submit_inverse_raw(req: RawTargetInverseRequest, background_tasks: BackgroundTasks) -> dict:
    """User-defined-target inverse solve (target editor / CSV import — see
    app/README.md). Shares the same job store/poll route as /api/inverse:
    poll GET /api/inverse/{job_id}; the result's ``presolve_gate`` field
    carries the T4 realisability verdict computed first, even on failure."""
    job = jobs.create_job()
    background_tasks.add_task(jobs.run_job, job.id, engine.run_inverse_raw, req)
    return {"job_id": job.id, "status": job.status}
