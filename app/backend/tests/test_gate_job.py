"""The job form of the realisability gate, and the screening configuration.

The gate spends two inviscid solves per CST coefficient. At order 6 that is 29
solves per presolve pass and 60 for the default two passes, measured 18.8 s
locally and, on the deployed free-tier container, more than the 600 s the
measurement was given. No fixed client timeout can cover that, which is why
the job form exists rather than a larger budget.
"""

from __future__ import annotations

import time

import pytest

from app import engine


@pytest.fixture
def gate_request(client):
    r = client.post("/api/analyze", json={"naca": "4412", "alpha": 3.0})
    assert r.status_code == 200
    d = r.json()
    return {
        "baseline": {"naca": "2412"},
        "target": {"x": d["x"], "cp": d["cp"]},
        "n": 6,
        "alpha_deg": 3.0,
        "alpha_free": True,
    }


@pytest.fixture(autouse=True)
def _clear():
    engine._GATE_CTX_CACHE.clear()  # noqa: SLF001 - the cache is under test
    yield
    engine._GATE_CTX_CACHE.clear()  # noqa: SLF001


def _poll(client, job_id, deadline_s=900):
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        r = client.get(f"/api/inverse/gate/{job_id}")
        assert r.status_code == 200
        p = r.json()
        if p["status"] in ("done", "error"):
            return p
        time.sleep(0.2)
    raise AssertionError("gate job did not finish")


def test_submit_accepts_and_returns_a_job_id(client, gate_request):
    r = client.post("/api/inverse/gate/submit", json=gate_request)
    assert r.status_code == 202
    assert r.json()["job_id"]


def test_unknown_gate_job_is_404(client):
    assert client.get("/api/inverse/gate/not-a-job").status_code == 404


def test_gate_job_completes_and_reports_its_configuration(client, gate_request):
    sub = client.post("/api/inverse/gate/submit", json=gate_request)
    done = _poll(client, sub.json()["job_id"])
    assert done["status"] == "done", done
    g = done["result"]
    assert isinstance(g["realisable"], bool)
    assert g["presolve_passes"] == 2
    assert g["screening"] is False


def test_gate_runs_at_study_fidelity(client, gate_request):
    """Both presolve knobs stay at study fidelity, and this is deliberate.

    A cheaper gate was tried: one presolve pass at the interactive paneling,
    3.2x faster. On a self-consistency target it agreed with the full verdict,
    which looked like justification, but the agreement was two errors
    cancelling. Isolated on a 4412 target against a 2412 baseline, dropping the
    second pass alone reports realisability 0.071 where two passes report
    0.036: across the 0.05 threshold, so the verdict inverts. The saving is not
    available without making the gate capable of the wrong answer.
    """
    from cins.config import load_config

    g = client.post("/api/inverse/gate", json=gate_request).json()
    assert g["npanel"] == load_config().paneling.npanel
    assert g["presolve_passes"] == 2


def test_repeat_gate_is_cached(client, gate_request):
    first = client.post("/api/inverse/gate", json=gate_request).json()
    assert first["cached"] is False
    t0 = time.perf_counter()
    second = client.post("/api/inverse/gate", json=gate_request).json()
    elapsed = time.perf_counter() - t0
    assert second["cached"] is True
    assert second["realisability"] == pytest.approx(first["realisability"], rel=1e-12)
    assert elapsed < 1.0, f"cached gate took {elapsed:.2f}s"


def test_cached_standalone_path_matches_the_uncached_one_exactly(client, gate_request):
    """The cache is the only saving taken, so it must be exact rather than
    approximate: the endpoint and the underlying gate must agree bit for bit."""
    from app.schemas import RawTargetInverseRequest

    req = RawTargetInverseRequest(**gate_request)
    served = engine.run_presolve_gate_screening(req)
    full = engine.run_presolve_gate_raw(req)["gate"]
    assert served["realisable"] == full["realisable"]
    assert served["realisability"] == pytest.approx(full["realisability"], rel=1e-12)


def test_the_solve_path_still_runs_the_full_presolve(client, gate_request):
    """run_inverse_raw's presolve output is the Newton solve's initial guess,
    so it must not be degraded by anything done for the standalone endpoint."""
    from app.schemas import RawTargetInverseRequest

    full = engine.run_presolve_gate_raw(RawTargetInverseRequest(**gate_request))["gate"]
    assert full["presolve_passes"] == 2


def test_polling_a_running_job_does_not_500(client):
    """Regression: the deployed poll answered 500 while the gate was running.

    jobs.run_job writes partial progress payloads into job.result so the
    inverse endpoint can show live stages. Those partials are shaped for the
    inverse payload, so validating one against this endpoint's response model
    fails and the poll returns 500 rather than "still running" - which is
    worse than the timeout it replaced, because the caller cannot wait either.
    """
    from app import jobs

    job = jobs.create_job()
    job.status = "running"
    job.phase = "presolve pass 1/2 (inviscid Cp + sensitivity matrix)"
    job.result = {"phase": job.phase, "stages": [], "realisability": None}

    r = client.get(f"/api/inverse/gate/{job.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["result"] is None
    assert body["phase"] == job.phase


def test_polling_a_running_analyze_job_does_not_500(client):
    from app import jobs

    job = jobs.create_job()
    job.status = "running"
    job.phase = "viscous solve"
    job.result = {"phase": job.phase}

    r = client.get(f"/api/analyze/{job.id}")
    assert r.status_code == 200, r.text
    assert r.json()["result"] is None
    assert r.json()["phase"] == "viscous solve"


def test_the_solve_reuses_the_gate_the_user_just_ran(client, gate_request):
    """The Inverse page's flow is "check realisability", then "run inverse
    solve", and run_inverse_raw starts by calling the same gate. Before the
    context was cached it repeated all 60 inviscid solves the user had just
    waited through, about 620 s on the free-tier container, before the first
    Newton iteration. That, not the Newton solve, is what exhausted the 1500 s
    watchdog in the field.
    """
    from app.schemas import RawTargetInverseRequest

    req = RawTargetInverseRequest(**gate_request)
    first = engine.run_presolve_gate_raw(req)
    assert first["cached"] is False

    second = engine.run_presolve_gate_raw(req)
    assert second["cached"] is True
    assert second["gate"]["realisability"] == pytest.approx(
        first["gate"]["realisability"], rel=1e-12
    )
    assert second["a0"] == pytest.approx(first["a0"], rel=1e-12)


def test_cached_context_is_isolated_from_caller_mutation(client, gate_request):
    """run_inverse_raw overwrites the nose coefficients in a0. If it were
    handed the cached array itself, the next caller would inherit that edit."""
    from app.schemas import RawTargetInverseRequest

    req = RawTargetInverseRequest(**gate_request)
    first = engine.run_presolve_gate_raw(req)
    original = float(first["a0"][0])
    first["a0"][0] = 999.0

    second = engine.run_presolve_gate_raw(req)
    assert float(second["a0"][0]) == pytest.approx(original, rel=1e-12)
