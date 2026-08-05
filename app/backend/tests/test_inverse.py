from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import engine  # noqa: E402 - path extended above
from cins.config import load_config  # noqa: E402


class _FakeFoil:
    def __init__(self, x: np.ndarray) -> None:
        self.x = x
        self.N = x.shape[1]


class _FakeGlob:
    def __init__(self, n: int) -> None:
        self.U = np.zeros((4, n))
        self.U[3] = np.linspace(0.5, 1.5, n)  # ue


class _FakeGeom:
    chord = 1.0


class _FakeOper:
    alpha = 2.0


class _FakeVsol:
    Xt = np.array([[0.10, 0.12], [0.10, 0.18]])  # [lower, upper] x [xi, x]


class _FakeMfoil:
    """Minimal stand-in for a live mfoil instance exposing exactly the
    attributes ``StageCapturingDiagnostics.record_iteration`` reads — lets the
    stage-capture contract be tested without running an actual (slow) Newton
    solve (dossier: this is app-side instrumentation, not solver physics)."""

    def __init__(self, n: int = 20) -> None:
        x = np.linspace(0, 1, n)
        y = 0.05 * np.sin(np.pi * x)
        self.foil = _FakeFoil(np.vstack([x, y]))
        self.glob = _FakeGlob(n)
        self.geom = _FakeGeom()
        self.oper = _FakeOper()
        self.vsol = _FakeVsol()
        self.param = object()


def test_stage_capturing_diagnostics_records_growing_stages(monkeypatch):
    """Item 1 of the app rich-features brief: StageCapturingDiagnostics must
    grow a ``stages`` list, one entry per ``record_iteration`` call, each with
    decimated coords + current-vs-target Cp at the target stations. Fast:
    exercises the class directly against a fake mfoil instance instead of
    running a real (multi-second) Newton solve."""
    fake_mod = types.SimpleNamespace(get_cp=lambda ue, param: (ue.copy(), None))
    monkeypatch.setattr(engine, "mfoil_module", lambda: fake_mod)

    m = _FakeMfoil(n=20)
    cfg = load_config()
    station_idx = np.array([2, 5, 8])
    cp_target = np.array([0.1, 0.2, 0.3])
    seen_progress: list[int] = []
    diag = engine.StageCapturingDiagnostics(
        cfg,
        get_mfoil=lambda: m,
        cp_target=cp_target,
        station_idx=station_idx,
        on_stage=lambda stages: seen_progress.append(len(stages)),
    )

    for it in range(3):
        diag.record_iteration(it, R_norm=1.0 / (it + 1), T_norm=0.5, G_norm=0.0)

    assert len(diag.stages) == 3
    assert seen_progress == [1, 2, 3]  # on_stage fired after every iteration
    for i, stage in enumerate(diag.stages):
        assert stage["it"] == i
        assert len(stage["coords"]) > 0
        assert len(stage["coords"][0]) == 2
        assert len(stage["cp_current"]) == 3
        assert stage["cp_target"] == cp_target.tolist()
        assert stage["alpha"] == pytest.approx(2.0)
        # _FakeVsol.Xt = [[lower_xi, lower_x], [upper_xi, upper_x]]; engine.py
        # reads xt[1,1] (upper x) and xt[0,1] (lower x) — same convention as
        # cins.solver.newton.solve_inverse's own transition_xt logging.
        assert stage["transition"] == {"upper": 0.18, "lower": 0.12}


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
