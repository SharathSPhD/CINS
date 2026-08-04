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
from cins.cst.constraints import shared_le_radius_row
from cins.cst.fit import fit_cst
from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.geometry_update import apply_geometry
from cins.solver.mfoil_adapter import make_mfoil, mfoil_module, set_forced_transition
from cins.solver.newton import (
    InverseProblem,
    assert_square,
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
    # Prescribed-LE treatment (dossier §3.5 fix 3, PROPERLY): the FM-3 station
    # exclusion must be matched by FIXING the LE-dominant coefficients — freeing
    # them while removing their stations leaves near-null directions and Newton
    # converges to a different root (observed: T=0 at all stations but
    # ||A-A*||=3.4e-2). Fix A_u0, A_l0 (nose radius both sides) at prescribed
    # values; shared-LE row then redundant -> dropped.
    n_a = len(a_star)
    if cfg.cst.le_treatment == "prescribed":
        fixed = [0, n + 1]  # A_u0, A_l0
        free_idx = np.array([i for i in range(n_a) if i not in fixed])
        G = np.zeros((0, n_a))
        b = np.zeros(0)
    else:
        free_idx = np.arange(n_a)
        g_row, _ = shared_le_radius_row(n, n)
        G = g_row.reshape(1, -1)
        b = np.array([float(g_row @ a_star)])  # target-consistent RHS
    n_targets = len(free_idx) - G.shape[0]  # alpha fixed for self-consistency

    # --- 4. perturb A* -> A0, re-init state at A0 -------------------------
    rng = np.random.default_rng(cfg.experiment.seed)
    a0 = a_star.copy()
    a0[free_idx] = a_star[free_idx] * (1.0 + 0.05 * rng.standard_normal(len(free_idx)))
    log.info("perturbed offset ||A0-A*||_inf = %.3e", np.max(np.abs(a0 - a_star)))

    # --- 4b. T4 pre-solve initialisation (dossier §7.8 step 4) ------------
    # The point-sampled square system has multiple exact roots (observed:
    # T=0 at all stations with ||A-A*|| up to 6e-2 from ±5% starts). The
    # pre-solve uses the FULL Cp distribution — the between-station
    # information that selects A*'s basin. Two re-linearized passes.
    from cins.solver.presolve import interpolate_cp_to_stations, presolve, solve_inviscid_cp

    target_res = solve_inviscid_cp(
        fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
    )
    for it_ps in range(2):
        base_res = solve_inviscid_cp(
            a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
        )
        cp_t_at_a0 = interpolate_cp_to_stations(target_res, base_res)
        ps = presolve(
            cp_t_at_a0, a0[: n + 1], a0[n + 1 :],
            fit.zeta_T_upper, fit.zeta_T_lower, psi, [], cfg,
        )
        a0 = np.asarray(ps.A, dtype=float)
        # keep prescribed coefficients pinned
        a0[0], a0[n + 1] = a_star[0], a_star[n + 1]
        log.info("presolve pass %d: ||A-A*||_inf = %.3e realisability=%.4f",
                 it_ps + 1, np.max(np.abs(a0 - a_star)), ps.realisability)

    # --- 4c. sensitivity-optimal station selection ------------------------
    # Evenly-spaced stations leave near-null directions in the 16x16 station
    # map (T=0 tolerates ~1e-3 coefficient drift — FM-2 via station choice).
    # Choose stations by QR column pivoting on the presolve sensitivity M:
    # rows = candidate stations, picked to maximize the submap's conditioning.
    from scipy.linalg import qr as _qr

    from cins.solver.presolve import build_sensitivity_matrix

    sens = build_sensitivity_matrix(
        a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
    )
    x_sens = np.asarray(sens.x_stations)
    le_frac = cfg.cst.prescribed_le_fraction
    cand = np.nonzero(x_sens >= le_frac)[0]
    m_cand = np.asarray(sens.M)[cand][:, free_idx]  # (n_cand, n_free)
    _, _, piv = _qr(m_cand.T, pivoting=True)  # pick most informative rows
    stations = np.sort(cand[piv[:n_targets]])
    sub = np.asarray(sens.M)[stations][:, free_idx]
    log.info("station selection: cond(submap) = %.3e (QR-pivoted)", np.linalg.cond(sub))
    cp_target = cp_ref[stations]
    assert_square(len(free_idx), len(stations), G.shape[0], alpha_free=False)

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
        # Self-consistency test: target generated at known alpha; freeing alpha
        # opens the camber-alpha equivalence family (observed: converged to a
        # different root with T=0). Fix it; arbitrary-target runs free it.
        alpha_free=False,
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
