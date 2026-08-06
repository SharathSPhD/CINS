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

    # The gate's realisability is an INVISCID-consistent quantity by ADR-0004,
    # and this target is viscous, so it gates as unrealisable by construction:
    # measured 0.0663 against a 0.05 threshold. ADR-0004 settles what that
    # means, having seen the same thing before ("...NOT target unrealisability.
    # The subsequent monolithic solve converged to 1e-11 - proof the target was
    # realisable"), and introduced model_gap as the viscous-consistent measure.
    # Asserting realisable is True here was left over from when this test used
    # an inviscid target; it cannot hold for a viscous one. The verdict must
    # still be reported on every result, which is what is checked.
    assert isinstance(result["presolve_gate"]["realisability"], float)
    assert result["model_gap"] is not None
    assert result["model_gap"] < 0.10, result["model_gap"]

    # What this test is named for, and never actually checked before.
    assert result["converged"] is True, result["notes"]
    assert result["iterations"] <= 15, result["iterations"]
    assert result["residual_history"][-1] < 1e-9

    # Recovery is asserted on the SHAPE, not on the coefficients. The CST basis
    # is ill-conditioned in A (dossier FM-2), so coefficients that differ by
    # 1.8e-2 describe surfaces that differ by well under a millichord: the
    # coefficient norm is not a meaningful accuracy statement for a target that
    # only ever constrained pressure. Measured max offset 0.417 mc with alpha
    # fixed and 0.479 mc with it free, against the 1 mc (0.1 percent chord) that
    # T2 allows a CST fit itself.
    fit = fit_cst(make_mfoil(naca="2412").geom.xpoint[0], make_mfoil(naca="2412").geom.xpoint[1], 6)
    psi = cosine_spacing(160)
    z_star = coords_from_A(
        fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi
    )[1]
    z_got = coords_from_A(
        np.asarray(result["A_upper"]), np.asarray(result["A_lower"]),
        fit.zeta_T_upper, fit.zeta_T_lower, psi,
    )[1]
    offset_mc = float(np.max(np.abs(z_got - z_star))) * 1000.0
    assert offset_mc < 2.0, f"recovered surface is {offset_mc:.3f} millichords from the target"
