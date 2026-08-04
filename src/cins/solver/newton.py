"""T5 — the monolithic extended Newton system (dossier §7.6).

Unknowns:   U (4·Nsys flow state) | α (1) | A_free (n_A_free CST coefficients)
Equations:  F (4·Nsys flow residual) | T (M target-Cp rows) | G (K constraint rows)

Squareness (FM-1):  M + K = n_A_free + 1, asserted at construction.

Jacobian blocks:
    ⎡ J_UU      J_Uα     J_UA  ⎤     J_UU  : mfoil's analytic R_V 4Nsys block
    ⎢ T_U        0        0    ⎥     J_Uα  : analytic (clalpha_residual, ue rows)
    ⎣  0         0        G    ⎦     J_UA  : central FD over A (T1-mandated)

Target rows compare Cp(U) at fixed node indices with the prescribed target, so
they depend on geometry only through U (∂T/∂A = 0 at fixed state). Stations in
the prescribed-LE region are excluded (FM-3 mitigation: the pathological rows
are removed, dossier §3.5 fix 3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu

from cins.config import CinsConfig
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.geometry_update import apply_geometry, dR_dA_fd, flow_residual
from cins.solver.mfoil_adapter import mfoil_module

log = logging.getLogger(__name__)


@dataclass
class InverseProblem:
    """Fully-specified monolithic inverse problem (all arrays validated)."""

    cp_target: np.ndarray          # (M,) target Cp at the selected station node indices
    station_idx: np.ndarray        # (M,) airfoil node indices of the target stations
    A0_upper: np.ndarray           # (n_u+1,) initial upper coefficients
    A0_lower: np.ndarray           # (n_l+1,) initial lower coefficients
    zeta_T_u: float
    zeta_T_l: float
    psi: np.ndarray                # CST sampling grid used for coords_from_A
    G: np.ndarray                  # (K, n_A_total) constraint rows over the FULL A vector
    b: np.ndarray                  # (K,)
    free_idx: np.ndarray           # indices into the stacked A vector that are unknowns
    alpha0: float = 0.0


@dataclass
class InverseResult:
    A_upper: np.ndarray
    A_lower: np.ndarray
    alpha: float
    converged: bool
    iterations: int
    residual_norms: list[float] = field(default_factory=list)
    convergence_order: float | None = None
    diagnostics_path: str | None = None


def select_target_stations(m, cfg: CinsConfig, n_stations: int) -> np.ndarray:
    """Pick target-station node indices: evenly spread in arc length over both
    surfaces, excluding the prescribed-LE region (FM-3) and the stagnation
    neighborhood. Deterministic for a given geometry/config."""
    x = m.foil.x[0] / m.geom.chord
    n_foil = m.foil.N
    le_frac = cfg.cst.prescribed_le_fraction if cfg.cst.le_treatment == "prescribed" else 0.0
    candidates = np.nonzero(x[:n_foil] >= le_frac)[0]
    # exclude the 2 nodes flanking stagnation (Istag) — rows scale badly there
    ist = set(int(i) for i in m.isol.Istag)
    candidates = np.array([i for i in candidates if i not in ist])
    if len(candidates) < n_stations:
        raise ValueError(f"only {len(candidates)} candidate stations for {n_stations} targets")
    pick = np.linspace(0, len(candidates) - 1, n_stations).round().astype(int)
    return candidates[np.unique(pick)]


def assert_square(n_free: int, n_targets: int, n_constraints: int) -> None:
    """FM-1 bookkeeping: M + K = n_A_free + 1 (the +1 is α). Raise loudly."""
    lhs, rhs = n_targets + n_constraints, n_free + 1
    log.info("DOF accounting: M=%d K=%d n_A_free=%d (+1 alpha)", n_targets, n_constraints, n_free)
    if lhs != rhs:
        raise ValueError(
            f"extended system not square: M+K={lhs} but n_A_free+1={rhs} "
            f"(M={n_targets}, K={n_constraints}, n_A_free={n_free})"
        )


def _flow_jacobian_blocks(m):
    """Assemble mfoil's analytic 4Nsys flow Jacobian (as solve_glob does) plus
    the analytic alpha column for the ue-closure rows."""
    mod = mfoil_module()
    nsys = m.glob.Nsys
    ue = m.glob.U[3].copy()
    ds = m.glob.U[1].copy()

    j_uu = sparse.lil_matrix((4 * nsys, 4 * nsys))
    j_uu[0 : 3 * nsys, :] = m.glob.R_U
    i_rows = slice(3 * nsys, 4 * nsys)
    ids = slice(1, 4 * nsys, 4)
    iue = slice(3, 4 * nsys, 4)
    ue_m = np.asarray(m.vsol.ue_m)
    j_uu[i_rows, iue] = sparse.identity(nsys) - ue_m @ np.diag(ds)
    j_uu[i_rows, ids] = -ue_m @ np.diag(ue)

    # analytic d(R_ue)/d(alpha): ueinv = uearef cos(a) + ... -> use mfoil's own helper
    _, ru_alpha, _ = mod.clalpha_residual(m)
    j_ualpha = np.zeros(4 * nsys)
    j_ualpha[3 * nsys : 4 * nsys] = np.asarray(ru_alpha).ravel()
    return j_uu.tocsr(), j_ualpha


def _target_rows(m, station_idx: np.ndarray, cp_target: np.ndarray):
    """T(U) = Cp(ue at stations) − Cp_target, with analytic ∂T/∂U (cp_ue on the
    ue slot of each station's state column)."""
    mod = mfoil_module()
    nsys = m.glob.Nsys
    ue_all = m.glob.U[3]
    cp_all, cp_ue_all = mod.get_cp(ue_all, m.param)
    r_t = cp_all[station_idx] - cp_target
    t_u = sparse.lil_matrix((len(station_idx), 4 * nsys))
    for k, i in enumerate(station_idx):
        t_u[k, 4 * i + 3] = cp_ue_all[i]
    return np.asarray(r_t), t_u.tocsr()


def solve_inverse(
    m,
    prob: InverseProblem,
    cfg: CinsConfig,
    diag: NewtonDiagnostics | None = None,
    run_dir=None,
    run_manifest: dict | None = None,
) -> InverseResult:
    """The monolithic CST–Newton inverse solve (dossier §7.6).

    `m` must hold a converged (or well-initialized) viscous state for the
    INITIAL geometry (A0) — use the T4 pre-solve + a direct solve to get there.
    Forced transition (ADR-0003) should already be active if configured.
    """
    mod = mfoil_module()
    n_u = len(prob.A0_upper)
    A = np.concatenate([prob.A0_upper, prob.A0_lower]).astype(float)
    n_free = len(prob.free_idx)
    n_t, n_k = len(prob.station_idx), prob.G.shape[0]
    assert_square(n_free, n_t, n_k)

    diag = diag or NewtonDiagnostics(config=cfg)
    diag.record_static(
        dof_accounting={
            "n_A_free": n_free, "M": n_t, "K": n_k,
            "squareness_residual": (n_t + n_k) - (n_free + 1),
        }
    )

    nsys = m.glob.Nsys
    n_flow = 4 * nsys
    g_free = prob.G[:, prob.free_idx]  # constraint block over free coefficients
    result_norms: list[float] = []
    converged = False
    it = 0

    for it in range(cfg.newton.max_iter):
        # --- assemble residuals -------------------------------------------
        r_flow = flow_residual(m)                       # (4Nsys,) rebuilds R/R_U
        r_t, t_u = _target_rows(m, prob.station_idx, prob.cp_target)
        r_g = prob.G @ A - prob.b

        r_full = np.concatenate([r_flow, r_t, r_g])
        rnorm = float(np.linalg.norm(r_full))
        result_norms.append(rnorm)

        xt = m.vsol.Xt.copy() if hasattr(m.vsol, "Xt") else None
        if rnorm < cfg.newton.rtol:
            converged = True
            diag.record_iteration(
                it=it, R_norm=float(np.linalg.norm(r_flow)),
                T_norm=float(np.linalg.norm(r_t)), G_norm=float(np.linalg.norm(r_g)),
                transition_xt=(float(xt[1, 1]), float(xt[0, 1])) if xt is not None else None,
            )
            break

        # --- assemble Jacobian --------------------------------------------
        j_uu, j_ualpha = _flow_jacobian_blocks(m)
        j_ua_full = dR_dA_fd(
            m, A[:n_u], A[n_u:], prob.zeta_T_u, prob.zeta_T_l, prob.psi,
            prob.free_idx, cfg.newton.fd_step,
        )  # (4Nsys, n_free)

        n_total = n_flow + 1 + n_free
        j = sparse.lil_matrix((n_flow + n_t + n_k, n_total))
        j[:n_flow, :n_flow] = j_uu
        j[:n_flow, n_flow] = j_ualpha.reshape(-1, 1)
        j[:n_flow, n_flow + 1 :] = j_ua_full
        j[n_flow : n_flow + n_t, :n_flow] = t_u
        j[n_flow + n_t :, n_flow + 1 :] = g_free
        j = j.tocsc()

        diag.record_iteration(
            it=it,
            R_norm=float(np.linalg.norm(r_flow)),
            T_norm=float(np.linalg.norm(r_t)),
            G_norm=float(np.linalg.norm(r_g)),
            jacobian=j if cfg.diagnostics.compute_expensive else None,
            dR_dA=j_ua_full,
            x_stations=m.foil.x[0] / m.geom.chord,
            transition_xt=(float(xt[1, 1]), float(xt[0, 1])) if xt is not None else None,
        )

        # --- solve ---------------------------------------------------------
        dv = -splu(j).solve(r_full)
        d_u = dv[:n_flow].reshape(nsys, 4).T  # mfoil layout (4, Nsys)
        d_alpha = float(dv[n_flow])
        d_a = dv[n_flow + 1 :]

        # --- limit + apply -------------------------------------------------
        # U block: reuse mfoil's under-relaxation machinery
        m.glob.dU = d_u
        m.glob.dalpha = d_alpha
        mod.update_state(m)

        # A block: separate, more permissive trust region (dossier §7.6)
        amax = float(np.max(np.abs(d_a))) if len(d_a) else 0.0
        scale = min(1.0, cfg.newton.a_trust_radius / amax) if amax > 0 else 1.0
        A[prob.free_idx] += scale * d_a
        diag_extra_omega = scale

        apply_geometry(m, A[:n_u], A[n_u:], prob.zeta_T_u, prob.zeta_T_l, prob.psi)
        mod.stagpoint_move(m)
        mod.update_transition(m)  # no-op under forced transition (ADR-0003)
        log.info("it=%d |R|=%.3e |T|=%.3e |G|=%.3e omega_A=%.2f",
                 it, np.linalg.norm(r_flow), np.linalg.norm(r_t), np.linalg.norm(r_g),
                 diag_extra_omega)

    order = diag.convergence_order_estimate()
    diag_path = None
    if run_dir is not None:
        report = diag.finalize(run_dir, run_manifest or {})
        diag_path = str(getattr(report, "path", run_dir))

    return InverseResult(
        A_upper=A[:n_u], A_lower=A[n_u:], alpha=float(m.oper.alpha),
        converged=converged, iterations=it + 1,
        residual_norms=result_norms, convergence_order=order,
        diagnostics_path=diag_path,
    )
