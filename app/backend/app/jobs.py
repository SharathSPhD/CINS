"""In-process job store for the long-running /api/inverse solve.

Deliberately the simplest thing that works for local-dev, single-worker
uvicorn (docs/PRD.md phase-1 scope: "local dev quality, production-shaped").
Jobs live in a module-level dict for the life of the process; nothing is
persisted. A single uvicorn worker (the default `uvicorn app.main:app`, no
`--workers`) is required for this store to be consistent: see app/README.md.

Phase/heartbeat/timeout (defect-fix, see app/backend/app/engine.py's
``on_progress`` callers): the underlying solve is genuinely slow: measured
locally at ~90s before the first Newton iteration and ~40s per iteration
thereafter (app/README.md documents ~10-20 min for a full job on Render's
free-tier 0.1-vCPU instance): not deadlocked. Rather than trying to make the
vendor solve faster (out of scope: vendor/mfoil/mfoil.py and src/cins/** are
never edited), this module makes the wait legible: every job tracks a
human-readable ``phase`` string and an ``updated_at`` heartbeat timestamp that
advance even before the first Newton-iteration ``stage`` exists, and a
watchdog thread marks the job ``error`` with an explicit reason after
``timeout_s`` instead of leaving it ``running`` forever.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "error"]

# Overridable via env (Render free tier is far slower than local dev; a fixed
# constant would either time out healthy slow runs or never fire locally).
# Default: 25 minutes: above the documented ~10-20 min free-tier full-job
# ceiling (app/README.md) with headroom, but still bounded so the UI is never
# stuck showing "running" indefinitely.
# Measured, not guessed. On the deployed free-tier container the pre-solve
# alone is about 620 s and the Newton solve follows it, and a real job was
# observed being killed here at 1500 s while still inside presolve pass 1 of 2.
# The pre-solve is now reused from the gate the user just ran, which removes
# most of that, but the watchdog must still sit above the case where it was not
# run first. This is a liveness guard against a job that will never answer, not
# a performance budget: erring long costs a stale "running" status, while
# erring short throws away work that was going to succeed, which is what
# happened.
DEFAULT_TIMEOUT_S = float(os.environ.get("CINS_INVERSE_TIMEOUT_S", "3600"))


@dataclass
class Job:
    id: str
    status: JobStatus = "queued"
    phase: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    timeout_s: float = DEFAULT_TIMEOUT_S
    timed_out: bool = False


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def create_job(timeout_s: float = DEFAULT_TIMEOUT_S) -> Job:
    job = Job(id=str(uuid.uuid4()), timeout_s=timeout_s)
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
    MFOIL_LOCK: a second job's status stays "running" (not "queued") the
    instant BackgroundTasks picks it up, even while it's actually waiting on
    the lock, since the queued->running transition happens in this function,
    not inside the lock. That's a cosmetic imprecision only; the *solve*
    itself is correctly serialized.

    ``fn`` is called with ``on_progress=<callback>``: ``engine.run_inverse``
    / ``engine.run_inverse_raw`` invoke it at every phase transition AND after
    every Newton iteration with a partial result payload (including the
    growing ``stages`` list and a ``phase`` string), which is written straight
    to ``job.result``/``job.phase`` here so GET /api/inverse/{job_id} reflects
    live progress WHILE the background task is still running.

    A watchdog thread marks the job ``error`` (with an explicit "timed out"
    reason, the last known phase, and how many Newton iterations completed)
    if it is still ``running`` after ``job.timeout_s`` seconds: the vendor
    solve itself cannot be safely killed mid-computation (it's a plain
    Python/numpy call, not cancellable), so the underlying thread keeps
    running to completion in the background, but the JOB the user is polling
    stops claiming to be "running" forever. See module docstring."""
    job = get_job(job_id)
    if job is None:
        logger.error("run_job: unknown job_id=%s", job_id)
        return
    job.status = "running"
    job.phase = "starting"
    job.updated_at = time.time()

    stop_watchdog = threading.Event()

    def _watchdog() -> None:
        if stop_watchdog.wait(job.timeout_s):
            return  # job finished (or errored) within the budget
        with _JOBS_LOCK:
            if job.status == "running":
                n_stages = len((job.result or {}).get("stages") or [])
                job.status = "error"
                job.timed_out = True
                job.error = (
                    f"timed out after {job.timeout_s:.0f}s "
                    f"(last phase: {job.phase!r}, {n_stages} Newton iteration(s) completed). "
                    "The solve is very likely still slow rather than stuck: this backend "
                    "instance may be far slower than local dev (see app/README.md's free-tier "
                    "latency note); retry, or raise CINS_INVERSE_TIMEOUT_S."
                )
                job.updated_at = time.time()

    watchdog = threading.Thread(target=_watchdog, name=f"job-watchdog-{job_id[:8]}", daemon=True)
    watchdog.start()

    def _on_progress(partial: dict[str, Any]) -> None:
        job.result = partial
        phase = partial.get("phase")
        if phase:
            job.phase = phase
        job.updated_at = time.time()

    try:
        result = fn(*args, on_progress=_on_progress, **kwargs)
        stop_watchdog.set()
        with _JOBS_LOCK:
            if not job.timed_out:
                job.result = result
                job.status = "done"
                job.phase = "done"
                job.updated_at = time.time()
    except Exception as exc:  # noqa: BLE001 - surface every failure to the poller
        stop_watchdog.set()
        logger.exception("inverse job %s failed", job_id)
        with _JOBS_LOCK:
            if not job.timed_out:
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = "error"
                job.phase = "error"
                job.updated_at = time.time()
