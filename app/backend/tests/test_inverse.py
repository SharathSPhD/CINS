from __future__ import annotations

import time

import pytest


def test_inverse_submit_returns_job_id(client):
    r = client.post("/api/inverse", json={"airfoil": "2412"})
    assert r.status_code == 202
    data = r.json()
    assert "job_id" in data
    assert data["status"] in ("queued", "running", "done")


def test_inverse_poll_unknown_job_is_404(client):
    r = client.get("/api/inverse/does-not-exist")
    assert r.status_code == 404


def test_inverse_bad_naca_code_is_422(client):
    r = client.post("/api/inverse", json={"airfoil": "99"})
    assert r.status_code == 422


@pytest.mark.slow
def test_inverse_full_solve_recovers_2412(client):
    """End-to-end: submit a self-consistency inverse (T7-style, cfg defaults)
    and poll until it finishes. Mirrors the T7 gate (docs/GATES.md): the
    monolithic Newton solve should converge in single-digit iterations."""
    r = client.post("/api/inverse", json={"airfoil": "2412"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    deadline = time.monotonic() + 600
    status = None
    payload = None
    while time.monotonic() < deadline:
        poll = client.get(f"/api/inverse/{job_id}")
        assert poll.status_code == 200
        payload = poll.json()
        status = payload["status"]
        if status in ("done", "error"):
            break
        time.sleep(2)

    assert status == "done", payload
    result = payload["result"]
    assert result["converged"] is True
    assert result["iterations"] <= 9
    assert result["A_upper"] is not None
    assert result["coords"] is not None
    assert result["release_verify"]["ok"] is True
    assert len(result["diagnostics"]) == result["iterations"]
