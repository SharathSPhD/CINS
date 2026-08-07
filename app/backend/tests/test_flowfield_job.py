"""The job form of the flow field, and its cache.

The default 60x40 grid measures 92.3 s on the deployed free-tier container
against the 90 s the synchronous client allowed. That is a failure on the
margin rather than on anything about the request, which is the least useful
kind: the work always completed, just barely too late to be collected.
"""

from __future__ import annotations

import time

import pytest

from app import engine


@pytest.fixture(autouse=True)
def _clear():
    engine._FLOWFIELD_CACHE.clear()  # noqa: SLF001 - the cache is under test
    yield
    engine._FLOWFIELD_CACHE.clear()  # noqa: SLF001


REQ = {"naca": "2412", "alpha": 4.0, "grid": {"nx": 20, "ny": 14}}


def _poll(client, job_id, deadline_s=600):
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        r = client.get(f"/api/flowfield/{job_id}")
        assert r.status_code == 200, r.text
        p = r.json()
        if p["status"] in ("done", "error"):
            return p
        time.sleep(0.2)
    raise AssertionError("flow field job did not finish")


def test_submit_accepts_and_returns_a_job_id(client):
    r = client.post("/api/flowfield/submit", json=REQ)
    assert r.status_code == 202
    assert r.json()["job_id"]


def test_unknown_flowfield_job_is_404(client):
    assert client.get("/api/flowfield/not-a-job").status_code == 404


def test_job_result_matches_the_synchronous_call(client):
    sync = client.post("/api/flowfield", json=REQ)
    assert sync.status_code == 200
    engine._FLOWFIELD_CACHE.clear()  # noqa: SLF001 - make the job really compute

    sub = client.post("/api/flowfield/submit", json=REQ)
    done = _poll(client, sub.json()["job_id"])
    assert done["status"] == "done", done
    assert done["result"]["speed"] == sync.json()["speed"]


def test_repeat_field_is_cached(client):
    first = client.post("/api/flowfield", json=REQ).json()
    assert first["cached"] is False
    t0 = time.perf_counter()
    second = client.post("/api/flowfield", json=REQ).json()
    elapsed = time.perf_counter() - t0
    assert second["cached"] is True
    assert second["speed"] == first["speed"]
    assert elapsed < 1.0


def test_polling_a_running_flowfield_job_does_not_500(client):
    """Same regression the analyze and gate polls had: run_job parks progress
    payloads in job.result, and those do not satisfy this response model."""
    from app import jobs

    job = jobs.create_job()
    job.status = "running"
    job.phase = "inviscid field"
    job.result = {"phase": "inviscid field"}

    r = client.get(f"/api/flowfield/{job.id}")
    assert r.status_code == 200, r.text
    assert r.json()["result"] is None
    assert r.json()["phase"] == "inviscid field"
