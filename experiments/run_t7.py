"""T7 falsifiable test driver (dossier §7.8).

1. Fit CST (n=8) to NACA 2412 -> A*.
2. Build the CST geometry, direct-solve viscous WITH forced trip -> Cp_target.
3. Perturb A* -> A0; run the monolithic inverse.
4. Success: ||A - A*||_inf < 1e-4, single-digit iterations, quadratic tail.

Run: .venv/bin/python experiments/run_t7.py [--verbose]
"""

from __future__ import annotations

import logging
import sys

import numpy as np

from cins.config import load_config
from cins.cst.fit import fit_cst
from cins.cst.geometry import cosine_spacing, coords_from_A
from cins.cst.constraints import shared_le_radius_row
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.mfoil_adapter import make_mfoil, mfoil_module, set_forced_transition
from cins.solver.geometry_update import apply_geometry
from cins.solver.newton import (
    InverseProblem,
    assert_square,
    select_target_stations,
    solve_inverse,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("t7")


def main() -> int:
    cfg = load_config()
    mod = mfoil_module()
    n = cfg.cst.n_upper
    psi = cosine_spacing(160)

    # --- 1. reference coefficients A* ------------------------------------
    m_ref = make_mfoil(naca="2412")
    X = m_ref.geom.xpoint
    fit = fit_cst(X[0], X[1], n)
    a_star = np.concatenate([fit.A_upper, fit.A_lower])
    log.info("A* fitted: n=%d, rms=%.2e", n, fit.rms)

    # --- 2. target Cp from the CST geometry (tripped, viscous) ------------
    Xc = coords_from_A(fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi)
    m = make_mfoil(coords=Xc)
    m.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
    m.solve()
    assert m.glob.conv, "direct solve (natural) failed"
    set_forced_transition(m, cfg.transition.xtr_upper, cfg.transition.xtr_lower)
    mod.solve_coupled(m)
    assert m.glob.conv, "direct tripped solve failed"
    mod.calc_force(m)
    cp_ref = np.asarray(m.post.cp).copy()
    log.info("target generated: cl=%.4f cd=%.5f (tripped)", m.post.cl, m.post.cd)

    # --- 3. stations + constraints (square system) ------------------------
    n_a = len(a_star)
    free_idx = np.arange(n_a)
    g_row, _ = shared_le_radius_row(n, n)
    b_val = float(g_row @ a_star)  # target-consistent RHS (see memory note)
    G = g_row.reshape(1, -1)
    b = np.array([b_val])
    n_targets = len(free_idx) + 1 - G.shape[0]
    stations = select_target_stations(m, cfg, n_targets)
    cp_target = cp_ref[stations]
    assert_square(len(free_idx), len(stations), G.shape[0])

    # --- 4. perturb A* -> A0, re-init state at A0 -------------------------
    rng = np.random.default_rng(cfg.experiment.seed)
    a0 = a_star * (1.0 + 0.05 * rng.standard_normal(n_a))
    log.info("start offset ||A0-A*||_inf = %.3e", np.max(np.abs(a0 - a_star)))

    apply_geometry(m, a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi)
    mod.solve_coupled(m)  # converge flow at the perturbed geometry (still tripped)
    assert m.glob.conv, "flow solve at perturbed start failed"

    # --- 5. monolithic inverse -------------------------------------------
    prob = InverseProblem(
        cp_target=cp_target,
        station_idx=stations,
        A0_upper=a0[: n + 1],
        A0_lower=a0[n + 1 :],
        zeta_T_u=fit.zeta_T_upper,
        zeta_T_l=fit.zeta_T_lower,
        psi=psi,
        G=G,
        b=b,
        free_idx=free_idx,
        alpha0=cfg.operating.alpha_deg,
    )
    diag = NewtonDiagnostics(config=cfg)
    res = solve_inverse(m, prob, cfg, diag=diag, run_dir="experiments/results/t7_naca2412",
                        run_manifest={"case": "t7_naca2412_selfconsistent"})

    # --- 6. verdict --------------------------------------------------------
    a_final = np.concatenate([res.A_upper, res.A_lower])
    err = float(np.max(np.abs(a_final - a_star)))
    log.info("RESULT: converged=%s iters=%d ||A-A*||_inf=%.3e order=%s",
             res.converged, res.iterations, err, res.convergence_order)
    log.info("residual history: %s", ["%.2e" % r for r in res.residual_norms])
    ok = res.converged and err < cfg.gates.t7_a_recovery_inf_norm \
        and res.iterations <= cfg.gates.t7_max_newton_iters
    log.info("T7 GATE: %s", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
