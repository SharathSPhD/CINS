"""The job form of /api/analyze, and the result cache behind it.

Both exist for the same reason: a viscous solve on the deployed free-tier
container measures around 115 s against 3.5 s locally, which is longer than
most default client and proxy timeouts. The job form removes the timeout as a
failure mode; the cache removes the wait entirely on a repeat.
"""

from __future__ import annotations

import time

import pytest

from app import engine


@pytest.fixture(autouse=True)
def _clear_cache():
    engine._ANALYZE_CACHE.clear()  # noqa: SLF001 - the cache is the subject here
    yield
    engine._ANALYZE_CACHE.clear()  # noqa: SLF001


def _poll(client, job_id, deadline_s=600):
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        r = client.get(f"/api/analyze/{job_id}")
        assert r.status_code == 200
        payload = r.json()
        if payload["status"] in ("done", "error"):
            return payload
        time.sleep(0.2)
    raise AssertionError("analyze job did not finish")


def test_submit_accepts_and_returns_a_job_id(client):
    """The submit contract: 202 with a job id and a non-terminal status, so the
    caller has something to poll rather than a connection to hold open.

    Wall-clock non-blocking is deliberately not asserted here. Starlette's
    TestClient drives the application in-process and runs BackgroundTasks
    before returning control, so a timing assertion in this harness measures
    the solve, not the handler, and would pass or fail on machine speed. The
    behaviour that matters is verified against the deployed service instead.
    """
    r = client.post(
        "/api/analyze/submit", json={"naca": "2412", "alpha": 2.0, "Re": 1e6}
    )
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"]
    assert body["status"] in ("queued", "running", "done")


def test_unknown_job_id_is_404(client):
    assert client.get("/api/analyze/not-a-job").status_code == 404


def test_job_reaches_done_and_carries_the_same_answer_as_the_sync_call(client):
    body = {"naca": "2412", "alpha": 2.0}  # inviscid: fast enough for CI
    sync = client.post("/api/analyze", json=body)
    assert sync.status_code == 200
    engine._ANALYZE_CACHE.clear()  # noqa: SLF001 - force the job to really solve

    sub = client.post("/api/analyze/submit", json=body)
    assert sub.status_code == 202
    done = _poll(client, sub.json()["job_id"])
    assert done["status"] == "done", done
    assert done["result"]["cl"] == pytest.approx(sync.json()["cl"], rel=1e-12)


def test_repeat_request_is_served_from_cache(client):
    body = {"naca": "0012", "alpha": 3.0}
    first = client.post("/api/analyze", json=body)
    assert first.status_code == 200
    assert first.json()["cached"] is False

    second = client.post("/api/analyze", json=body)
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["cl"] == pytest.approx(first.json()["cl"], rel=1e-12)


def test_cache_distinguishes_requests_that_differ(client):
    a = client.post("/api/analyze", json={"naca": "0012", "alpha": 3.0}).json()
    b = client.post("/api/analyze", json={"naca": "0012", "alpha": 5.0}).json()
    assert b["cached"] is False
    assert a["cl"] != b["cl"]


def test_response_reports_the_paneling_actually_used(client):
    from cins.config import load_config

    r = client.post("/api/analyze", json={"naca": "2412", "alpha": 2.0}).json()
    assert r["npanel"] == load_config().paneling.npanel_interactive


def test_explicit_npanel_overrides_the_interactive_default(client):
    from cins.config import load_config

    study = load_config().paneling.npanel
    r = client.post(
        "/api/analyze", json={"naca": "2412", "alpha": 2.0, "npanel": study}
    ).json()
    assert r["npanel"] == study
