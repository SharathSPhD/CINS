from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app import engine, jobs
from app.schemas import (
    AnalyzeJobResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzeSubmitResponse,
)

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> dict:
    """Synchronous solve. Retained for scripted callers and for the cases that
    are genuinely quick (inviscid, or a cache hit). Interactive clients should
    prefer the job form below: on the free-tier container a viscous solve
    measures around 115 s, which is longer than most default client and proxy
    timeouts, so a synchronous request is the one shape of this call that can
    fail for reasons that have nothing to do with the solve."""
    try:
        return engine.run_analyze(req)
    except engine.EngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # unexpected mfoil/engine failure
        raise HTTPException(
            status_code=400, detail=f"analyze failed: {type(exc).__name__}: {exc}"
        ) from exc


@router.post("/analyze/submit", response_model=AnalyzeSubmitResponse, status_code=202)
def submit_analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks) -> dict:
    """Start the solve and return immediately with a job id, the same pattern
    the inverse endpoints use. Poll GET /api/analyze/{job_id}.

    This is what makes the wait survivable: nothing has to be held open for the
    duration, so a slow container costs the user time rather than an error, and
    the elapsed time is reported instead of guessed at."""
    job = jobs.create_job()
    background_tasks.add_task(jobs.run_job, job.id, engine.run_analyze, req)
    return {"job_id": job.id, "status": job.status}


@router.get("/analyze/{job_id}", response_model=AnalyzeJobResponse)
def poll_analyze(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id {job_id!r}")
    return {
        "job_id": job.id,
        "status": job.status,
        # Only once done. run_job writes partial progress payloads into
        # job.result while the task runs (that is what makes the inverse
        # endpoint's live stage list work), and those partials are shaped for
        # the inverse payload, not for this response model. Returning one here
        # fails response validation and the poll answers 500, which is worse
        # than the timeout it replaced: the caller cannot even wait properly.
        "result": job.result if job.status == "done" else None,
        "error": job.error,
        "phase": job.phase,
    }
