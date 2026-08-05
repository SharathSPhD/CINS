from __future__ import annotations

import time

import numpy as np
import pytest

from cins.solver.mfoil_adapter import make_mfoil, mfoil_module


def _naca2412_inviscid_target():
    m = make_mfoil(naca="2412")
    m.setoper(alpha=2.0)
    mfoil_module().solve_inviscid(m)
    return np.asarray(m.foil.x[0]).tolist(), np.asarray(m.post.cp).tolist()


def test_presolve_gate_raw_self_consistent_target_is_realisable(client):
    """A NACA 2412 baseline against its OWN inviscid Cp should gate as
    realisable (small residual) — the identity case."""
    x, cp = _naca2412_inviscid_target()
    r = client.post(
        "/api/inverse/gate",
        json={
            "baseline": {"naca": "2412"},
            "target": {"x": x, "cp": cp},
            "n": 6,
            "alpha_deg": 2.0,
            "alpha_free": True,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["realisable"] is True
    assert data["realisability"] < 0.02
    assert len(data["A_upper_init"]) == 7


def test_presolve_gate_raw_bad_target_length_is_422(client):
    r = client.post(
        "/api/inverse/gate",
        json={
            "baseline": {"naca": "2412"},
            "target": {"x": [0.0, 0.1, 0.2], "cp": [0.0, 0.1, 0.2]},
        },
    )
    assert r.status_code == 422


def test_presolve_gate_raw_needs_exactly_one_target_kind(client):
    x, cp = _naca2412_inviscid_target()
    r = client.post(
        "/api/inverse/gate",
        json={
            "baseline": {"naca": "2412"},
            "target": {"x": x, "cp": cp, "ue_over_vinf": [1.0] * len(x)},
        },
    )
    assert r.status_code == 422


def test_submit_inverse_raw_returns_job_id(client, monkeypatch):
    """Job-plumbing only — stubs ``engine.run_inverse_raw`` so this stays fast
    and does not tie up ``MFOIL_LOCK`` in a background thread for the
    duration of a real (potentially slow, see test_inverse_raw_recovers_...
    below) Newton solve while later tests in this process run."""
    from app import engine

    def _fast_stub(req, cell_name="api-inverse-raw"):
        return {
            "converged": True, "iterations": 1, "alpha": 2.0,
            "A_upper": [0.1], "A_lower": [-0.1], "coords": [[0.0, 0.0]],
            "residual_history": [1e-11], "convergence_order": None,
            "release_verify": None, "realisability": 0.01, "model_gap": None,
            "submap_cond": None, "notes": [], "dof_check_error": None,
            "wall_time_s": 0.01, "diagnostics": [], "manifest": {},
            "presolve_gate": {"realisability": 0.01, "realisable": True, "kkt_cond": 1.0},
        }

    monkeypatch.setattr(engine, "run_inverse_raw", _fast_stub)

    x, cp = _naca2412_inviscid_target()
    r = client.post(
        "/api/inverse/raw",
        json={"baseline": {"naca": "2412"}, "target": {"x": x, "cp": cp}, "n": 6},
    )
    assert r.status_code == 202
    data = r.json()
    assert "job_id" in data
    assert data["status"] in ("queued", "running", "done")

    # poll reuses the shared /api/inverse/{job_id} route
    poll = client.get(f"/api/inverse/{data['job_id']}")
    assert poll.status_code == 200
    assert poll.json()["status"] in ("queued", "running", "done", "error")


@pytest.mark.slow
def test_inverse_raw_recovers_self_consistent_target(client):
    """End-to-end: a raw (user-supplied) target that happens to equal NACA
    2412's own inviscid Cp should be recovered by the Newton solve, and the
    presolve_gate must be present on the result regardless of outcome."""
    x, cp = _naca2412_inviscid_target()
    r = client.post(
        "/api/inverse/raw",
        json={
            "baseline": {"naca": "2412"},
            "target": {"x": x, "cp": cp},
            "n": 6,
            "alpha_deg": 2.0,
            "alpha_free": True,
        },
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    deadline = time.monotonic() + 900
    status = None
    payload = None
    while time.monotonic() < deadline:
        poll = client.get(f"/api/inverse/{job_id}")
        assert poll.status_code == 200
        payload = poll.json()
        status = payload["status"]
        if status in ("done", "error"):
            break
        time.sleep(3)

    assert status == "done", payload
    result = payload["result"]
    assert result["presolve_gate"] is not None
    assert result["presolve_gate"]["realisable"] is True
