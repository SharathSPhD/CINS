"""Target-station placement under a prescribed leading edge.

Runs the same self-consistency inverse solve twice, changing exactly one
thing: whether the QR candidate set for target stations is restricted to
``x >= cfg.cst.prescribed_le_fraction``. Everything else, including the
starting point, is identical between the two cells.

The question is identifiability rather than convergence. With the leading
edge prescribed, A_u0 and A_l0 are given rather than solved, so a target row
placed inside the prescribed region constrains pressure over a piece of
surface that cannot move. Both cells converge; only one recovers the
generating geometry.

Writes an immutable manifest (config hash, git SHA, seed) with the results to
``experiments/results/le_stations/result.json``, which is what
``cins.benchmarks.paper_figures_theory.fig_le_identifiability`` and the paper
table read. Nothing here is hand-entered.

Run:  .venv/bin/python experiments/run_le_stations.py
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.linalg import qr as _qr

from cins.config import load_config
from cins.cst.fit import fit_cst
from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.solver.mfoil_adapter import (
    make_mfoil,
    mfoil_module,
    refresh_post,
    release_transition,
    set_forced_transition,
)
from cins.solver.newton import (
    InverseProblem,
    interpolate_cp_at_stations,
    solve_inverse,
    stations_from_indices,
)
from cins.solver.presolve import build_sensitivity_matrix

OUT_DIR = Path("experiments/results/le_stations")
SEED = 42
N_ORDER = 6
PERTURB = 0.004  # start offset applied to the generating coefficients

log = logging.getLogger(__name__)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:  # pragma: no cover - not worth failing a run over
        return "unknown"


def _build_target(cfg, n: int):
    """Viscous, tripped target generated from the CST reconstruction itself,
    so the answer is both known and exactly representable (T7 protocol)."""
    mod = mfoil_module()
    X = make_mfoil(naca="2412").geom.xpoint
    fit = fit_cst(X[0], X[1], n)
    psi = cosine_spacing(160)
    coords = coords_from_A(
        fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi
    )
    m = make_mfoil(coords=coords)
    m.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
    m.solve()
    assert m.glob.conv, "target baseline solve failed"
    set_forced_transition(m, cfg.transition.xtr_upper, cfg.transition.xtr_lower)
    try:
        mod.solve_coupled(m)
        refresh_post(m)
        assert m.glob.conv, "tripped target solve failed"
        tx = np.asarray(m.foil.x[0])
        tcp = np.asarray(m.post.cp)[: m.foil.N]
    finally:
        release_transition()
    return fit, psi, tx, tcp


def _run_cell(cfg, fit, psi, tx, tcp, a0, restrict: bool) -> dict:
    mod = mfoil_module()
    n_u = n_l = N_ORDER
    n_a = n_u + n_l + 2
    free_idx = np.array([i for i in range(n_a) if i not in (0, n_u + 1)])
    le_frac = float(cfg.cst.prescribed_le_fraction)

    sens = build_sensitivity_matrix(
        a0[: n_u + 1], a0[n_u + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
    )
    xs = np.asarray(sens.x_stations)
    n_pick = len(free_idx)  # alpha fixed, no constraint rows

    if restrict:
        cand = np.nonzero(xs >= le_frac)[0]
    else:
        cand = np.arange(xs.size)
    _, _, piv = _qr(sens.M[cand][:, free_idx].T, pivoting=True)
    stations = np.sort(cand[piv[:n_pick]])
    submap_cond = float(np.linalg.cond(sens.M[stations][:, free_idx]))

    ss, sx = stations_from_indices(
        sens.x_stations, stations, le_idx=sens.baseline.le_idx
    )
    cp_target = interpolate_cp_at_stations(tx, tcp, ss, sx)

    coords0 = coords_from_A(
        a0[: n_u + 1], a0[n_u + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi
    )
    m = make_mfoil(coords=coords0, npanel=cfg.paneling.npanel)
    m.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
    m.solve()
    assert m.glob.conv, "initial solve failed"
    set_forced_transition(m, cfg.transition.xtr_upper, cfg.transition.xtr_lower)
    try:
        mod.solve_coupled(m)
        refresh_post(m)
        assert m.glob.conv, "tripped initial solve failed"

        prob = InverseProblem(
            cp_target=cp_target, station_surface=ss, station_x=sx,
            A0_upper=a0[: n_u + 1], A0_lower=a0[n_u + 1 :],
            zeta_T_u=fit.zeta_T_upper, zeta_T_l=fit.zeta_T_lower, psi=psi,
            G=np.zeros((0, n_a)), b=np.zeros(0), free_idx=free_idx,
            alpha0=cfg.operating.alpha_deg, alpha_free=False,
        )
        res = solve_inverse(m, prob, cfg)
    finally:
        release_transition()

    A = np.concatenate([res.A_upper, res.A_lower])
    A_star = np.concatenate([fit.A_upper, fit.A_lower])
    z_star = coords_from_A(
        fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi
    )[1]
    z_got = coords_from_A(
        res.A_upper, res.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi
    )[1]

    return {
        "restrict_le_stations": restrict,
        "converged": bool(res.converged),
        "iterations": int(res.iterations),
        "final_residual": float(res.residual_norms[-1]),
        "err_free_inf": float(np.max(np.abs(A[free_idx] - A_star[free_idx]))),
        "err_all_inf": float(np.max(np.abs(A - A_star))),
        "max_surface_offset_mc": float(np.max(np.abs(z_got - z_star))) * 1000.0,
        "submap_cond": submap_cond,
        "n_candidates": int(cand.size),
        "n_stations": int(stations.size),
        "station_x": [float(v) for v in sx],
        "residual_history": [float(v) for v in res.residual_norms],
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    fit, psi, tx, tcp = _build_target(cfg, N_ORDER)

    # One shared, reproducible starting point for both cells.
    rng = np.random.default_rng(SEED)
    A_star = np.concatenate([fit.A_upper, fit.A_lower])
    a0 = A_star + PERTURB * rng.standard_normal(A_star.size)

    cells = {}
    for restrict in (False, True):
        key = "restricted" if restrict else "unrestricted"
        log.info("running cell: %s", key)
        cells[key] = _run_cell(cfg, fit, psi, tx, tcp, a0.copy(), restrict)
        log.info(
            "  converged=%s iters=%d err_free_inf=%.3e offset=%.4f mc cond=%.4g",
            cells[key]["converged"], cells[key]["iterations"],
            cells[key]["err_free_inf"], cells[key]["max_surface_offset_mc"],
            cells[key]["submap_cond"],
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "cell_name": "le_stations",
        "description": (
            "Target-station placement under a prescribed leading edge: "
            "unrestricted QR candidates against candidates restricted to "
            "x >= prescribed_le_fraction. Only the candidate set differs."
        ),
        "cells": cells,
        "start_offset_inf": float(np.max(np.abs(a0 - A_star))),
        "manifest": {
            "config_hash": cfg.config_hash(),
            "git_sha": _git_sha(),
            "seed": SEED,
            "n_order": N_ORDER,
            "perturbation": PERTURB,
            "prescribed_le_fraction": float(cfg.cst.prescribed_le_fraction),
            "alpha_deg": float(cfg.operating.alpha_deg),
            "Re": float(cfg.operating.Re),
            "transition_mode": cfg.transition.mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    out = OUT_DIR / "result.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
