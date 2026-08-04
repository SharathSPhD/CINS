"""In-process job store for the long-running /api/inverse solve.

Deliberately the simplest thing that works for local-dev, single-worker
uvicorn (docs/PRD.md phase-1 scope: "local dev quality, production-shaped").
Jobs live in a module-level dict for the life of the process; nothing is
persisted. A single uvicorn worker (the default `uvicorn app.main:app`, no
`--workers`) is required for this store to be consistent — see app/README.md.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "error"]


@dataclass
class Job:
    id: str
    status: JobStatus = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def create_job() -> Job:
    job = Job(id=str(uuid.uuid4()))
    with _JOBS_LOCK:
        _JOBS[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def run_job(job_id: str, fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> None:
    """Executed by FastAPI's BackgroundTasks after the submit response is
    already sent. Any two /api/inverse submissions serialize naturally here
    because `fn` (engine.run_inverse) itself blocks on the process-global
    MFOIL_LOCK — a second job's status stays "running" (not "queued") the
    instant BackgroundTasks picks it up, even while it's actually waiting on
    the lock, since the queued->running transition happens in this function,
    not inside the lock. That's a cosmetic imprecision only; the *solve*
    itself is correctly serialized."""
    job = get_job(job_id)
    if job is None:
        logger.error("run_job: unknown job_id=%s", job_id)
        return
    job.status = "running"
    try:
        job.result = fn(*args, **kwargs)
        job.status = "done"
    except Exception as exc:  # noqa: BLE001 - surface every failure to the poller
        logger.exception("inverse job %s failed", job_id)
        job.error = f"{type(exc).__name__}: {exc}"
        job.status = "error"
