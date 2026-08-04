from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app import engine, jobs
from app.schemas import InverseJobResponse, InverseRequest, InverseSubmitResponse

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
    return {"job_id": job.id, "status": job.status, "result": job.result, "error": job.error}
