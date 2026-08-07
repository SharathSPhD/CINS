from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app import engine, jobs
from app.schemas import (
    FlowFieldJobResponse,
    FlowFieldRequest,
    FlowFieldResponse,
    FlowFieldSubmitResponse,
)

router = APIRouter(prefix="/api", tags=["flowfield"])


@router.post("/flowfield", response_model=FlowFieldResponse)
def flowfield(req: FlowFieldRequest) -> dict:
    """Inviscid velocity/Cp field on a grid, for client-side vector/contour
    rendering. Inviscid only; grid size is capped server-side (see
    app/backend/app/engine.py::_FLOWFIELD_MAX_CELLS)."""
    try:
        return engine.run_flowfield(req)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"flowfield failed: {type(exc).__name__}: {exc}"
        ) from exc


@router.post("/flowfield/submit", response_model=FlowFieldSubmitResponse, status_code=202)
def submit_flowfield(req: FlowFieldRequest, background_tasks: BackgroundTasks) -> dict:
    """Start the field and return a job id. Poll GET /api/flowfield/{job_id}.

    The default 60x40 grid measures 92.3 s on the deployed free-tier container
    against the 90 s the client allowed, so the synchronous form fails on a
    margin rather than on anything about the request. This form has no margin
    to lose."""
    job = jobs.create_job()
    background_tasks.add_task(jobs.run_job, job.id, engine.run_flowfield, req)
    return {"job_id": job.id, "status": job.status}


@router.get("/flowfield/{job_id}", response_model=FlowFieldJobResponse)
def poll_flowfield(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id {job_id!r}")
    return {
        "job_id": job.id,
        "status": job.status,
        # Only once done: run_job parks progress payloads in job.result and
        # they do not satisfy this response model (see the analyze router).
        "result": job.result if job.status == "done" else None,
        "error": job.error,
        "phase": job.phase,
    }
