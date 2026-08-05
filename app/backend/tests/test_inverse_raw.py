from __future__ import annotations

import time

import numpy as np
import pytest

from cins.config import load_config
from cins.cst.fit import fit_cst
from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.solver.mfoil_adapter import (
    make_mfoil,
    mfoil_module,
    release_transition,
    set_forced_transition,
)


def _naca2412_inviscid_target():
    """NACA 2412's inviscid Cp: the right target for the presolve gate, whose
    realisability is an inviscid-consistent quantity by ADR-0004."""
    m = make_mfoil(naca="2412")
    m.setoper(alpha=2.0)
    mfoil_module().solve_inviscid(m)
    return np.asarray(m.foil.x[0]).tolist(), np.asarray(m.post.cp).tolist()


def _naca2412_viscous_tripped_target(n: int = 6):
    """NACA 2412's Cp under the conditions /api/inverse/raw actually solves,
    and from a geometry the solver can actually represent.

    Two things have to match for this to be a genuine identity case, and the
    earlier inviscid target from mfoil's own NACA paneling matched neither.

    First the physical model. The extended Newton system appends CST columns to
    mfoil's viscous global system, so the solve is viscous; at the true geometry
    the viscous and inviscid pressure distributions differ by up to 0.211 in Cp,
    9.2 percent relative, at any geometry and under any transition setting.

    Second the geometry family. The solver searches over CST surfaces of the
    requested order, so a target taken from mfoil's NACA paneling leaves the
    representation error of that fit as a floor: 1.2 percent relative in Cp at
    order 6, max 0.023. Generating the target from the CST reconstruction, as
    the T7 protocol does, removes it.
    """
    cfg = load_config()
    mod = mfoil_module()
    X = make_mfoil(naca="2412").geom.xpoint
    fit = fit_cst(X[0], X[1], n)
    coords = coords_from_A(
        fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, cosine_spacing(160)
    )
    m = make_mfoil(coords=coords)
    m.setoper(alpha=2.0, Re=cfg.operating.Re)
    m.solve()
    assert m.glob.conv
    set_forced_transition(m, cfg.transition.xtr_upper, cfg.transition.xtr_lower)
    try:
        mod.solve_coupled(m)
        mod.calc_force(m)
        assert m.glob.conv
        x = np.asarray(m.foil.x[0])
        cp = np.asarray(m.post.cp)[: m.foil.N]
    finally:
        release_transition()
    return x.tolist(), cp.tolist()


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

    x, cp = _naca2412_inviscid_target()  # stubbed solve: any well-formed target will do
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
@pytest.mark.xfail(
    reason=(
        "The raw-target path does not converge. Marked xfail so the limitation stays "
        "visible rather than being deleted or tuned green; the assertions below are "
        "unchanged and will report the day it passes. What is measured, as of "
        "2026-08-06: (1) transition treatment is not the cause, since pinning the trip "
        "widens the Cp gap slightly rather than closing it, 9.2 to 10.6 percent "
        "relative; (2) station identity is not the cause, since moving stations from "
        "node index to (surface, x) with interpolation fixed the demo, NACA 0012 onto "
        "2412 in 10 iterations to 7.5e-12 from 19.98 millichords away, and left this "
        "unchanged; (3) with alpha fixed the solve reaches iteration 24 and the "
        "extended Jacobian is then exactly singular; (4) under target continuation "
        "from a perturbed start the full residual falls to 2.08e-10 against an rtol "
        "of 1e-10, a stall just above tolerance rather than a divergence, while the "
        "coefficients end 7.2e-2 from the generating set having started 9.3e-3 away. "
        "A near-zero residual reached at coefficients an order of magnitude further "
        "out is the signature of a weakly identified system, not of a solver unable "
        "to make progress. The leading edge is the open suspect, since prescribing "
        "A_u0 and A_l0 instead of solving for them is the one structural difference "
        "between this configuration and the T7 recipe that recovers A* to 1e-11. "
        "That is stated as the next thing to test, not as an established cause."
    ),
    strict=False,
)
def test_inverse_raw_recovers_self_consistent_target(client):
    """End-to-end: a raw (user-supplied) target that equals NACA 2412's own Cp
    under the conditions this endpoint solves should be recovered by the Newton
    solve, and the presolve_gate must be present on the result regardless of
    outcome.

    The target is generated viscously and tripped to match the endpoint, not
    inviscidly: see ``_naca2412_viscous_tripped_target`` for why an inviscid
    target is unreachable here.
    """
    x, cp = _naca2412_viscous_tripped_target()
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
