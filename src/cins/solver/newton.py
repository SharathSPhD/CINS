"""T5 — the monolithic extended Newton system (dossier §7.6).

Unknowns:   U (4·Nsys flow state) | α (1) | A_free (n_A_free CST coefficients)
Equations:  F (4·Nsys flow residual) | T (M target-Cp rows) | G (K constraint rows)

Squareness (FM-1):  M + K = n_A_free + 1, asserted at construction.

Jacobian blocks:
    ⎡ J_UU      J_Uα     J_UA  ⎤     J_UU  : mfoil's analytic R_V 4Nsys block
    ⎢ T_U        0        0    ⎥     J_Uα  : analytic (clalpha_residual, ue rows)
    ⎣  0         0        G    ⎦     J_UA  : central FD over A (T1-mandated)

Target rows compare Cp(U) at fixed PHYSICAL stations -- a (surface, x/c) pair,
not a panel node index -- with the prescribed target (2026-08-05 fix: a node
index only means the same station while the geometry never moves; the whole
point of an inverse solve is that it does). The current Cp at a station is
linearly interpolated between the two panel nodes bracketing its x on the
CURRENT geometry's own surface, so a station keeps its physical meaning as A
(and therefore the paneling) changes across Newton iterations. This still
depends on geometry only through U at fixed A (∂T/∂A = 0 at fixed state): the
interpolation weight is a function of node x-positions, which are held fixed
within one Newton linearization exactly like every other geometry-dependent
quantity in this block. Stations in the prescribed-LE region are excluded
(FM-3 mitigation: the pathological rows are removed, dossier §3.5 fix 3).
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

    cp_target: np.ndarray          # (M,) target Cp at the selected stations
    station_surface: np.ndarray    # (M,) "lower"/"upper" -- which surface each station is on
    station_x: np.ndarray          # (M,) x/c of each station on its own surface (physical,
                                    # NOT a panel node index -- see module docstring)
    A0_upper: np.ndarray           # (n_u+1,) initial upper coefficients
    A0_lower: np.ndarray           # (n_l+1,) initial lower coefficients
    zeta_T_u: float
    zeta_T_l: float
    psi: np.ndarray                # CST sampling grid used for coords_from_A
    G: np.ndarray                  # (K, n_A_total) constraint rows over the FULL A vector
    b: np.ndarray                  # (K,)
    free_idx: np.ndarray           # indices into the stacked A vector that are unknowns
    alpha0: float = 0.0
    alpha_free: bool = True   # False: alpha fixed (self-consistency tests) — removes
                              # the camber-alpha equivalence null direction


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


def assert_square(n_free: int, n_targets: int, n_constraints: int, alpha_free: bool = True) -> None:
    """FM-1 bookkeeping: M + K = n_A_free (+1 if α free). Raise loudly."""
    n_alpha = 1 if alpha_free else 0
    lhs, rhs = n_targets + n_constraints, n_free + n_alpha
    log.info("DOF accounting: M=%d K=%d n_A_free=%d (+%d alpha)",
             n_targets, n_constraints, n_free, n_alpha)
    if lhs != rhs:
        raise ValueError(
            f"extended system not square: M+K={lhs} but n_A_free+n_alpha={rhs} "
            f"(M={n_targets}, K={n_constraints}, n_A_free={n_free})"
        )


def recover_omega(
    alpha_before: float,
    alpha_after: float,
    d_alpha: float,
    th_before: np.ndarray,
    th_after: np.ndarray,
    d_th: np.ndarray,
) -> float:
    """Recover the under-relaxation ω mfoil's update_state actually applied.

    Primary channel: α (applied as ω·dα, untouched by post-update repairs).
    Fallback (α fixed): the θ row — update_state's Hk/ctau repairs modify only
    ds and ctau, never θ (verified against vendor update_state, review batch
    2026-08-04). Result clipped to [0, 1]; ω=0 (full rejection) propagates so
    the A step is frozen with the state step — a deliberate design choice.
    """
    if abs(d_alpha) > 1e-14:
        omega = (alpha_after - alpha_before) / d_alpha
    else:
        k = int(np.argmax(np.abs(d_th)))
        omega = (th_after[k] - th_before[k]) / d_th[k] if d_th[k] != 0 else 1.0
    return float(np.clip(omega, 0.0, 1.0))


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

    # analytic d(R_ue)/d(alpha): R_ue = ue - (ueinv + ...) with
    # ueinv = ueinvref @ [cos(a), sin(a)]  ->  dR_ue/da = -ueinvref @ [-sin, cos] * pi/180
    # Assembled directly: vendor get_ueinvref's viscous branch is broken as shipped
    # (mfoil.py:598 builds uearef transposed (2,N) vs the (N,2) lines 601/604 expect),
    # and clalpha_residual's else-branch has a np.zeros(Nsys,1) bug. ADR-0002 family.
    alpha = m.oper.alpha
    uearef = np.asarray(m.isol.gamref) * np.asarray(m.isol.sgnue)[:, None]  # (N,2)
    uewref = np.asarray(m.isol.uewiref).copy()  # (Nw,2)
    if uewref.size:
        uewref[0, :] = uearef[-1, :]  # upper-surface/wake continuity
        ueinvref = np.vstack([uearef, uewref])
    else:
        ueinvref = uearef
    ru_alpha = -ueinvref @ np.array([-mod.sind(alpha), mod.cosd(alpha)]) * np.pi / 180.0
    j_ualpha = np.zeros(4 * nsys)
    j_ualpha[3 * nsys : 4 * nsys] = ru_alpha.ravel()
    return j_uu.tocsr(), j_ualpha


def _split_ascending_with_nodes(
    x: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split full-loop node indices 0..N-1 into lower/upper x-ascending
    branches, each carrying its ORIGINAL node index (needed to address the
    right ue slot in the flow-state vector). Same split-at-argmin(x),
    reverse-the-descending-branch convention as
    ``cins.solver.presolve._split_ascending`` / ``app.engine._split_ascending``.

    Returns (idx_lower_asc, x_lower_asc, idx_upper_asc, x_upper_asc).
    """
    le_idx = int(np.argmin(x))
    idx_lo = np.arange(le_idx + 1)
    idx_up = np.arange(le_idx, x.size)
    x_lo, x_up = x[idx_lo], x[idx_up]
    if x_lo.size >= 2 and x_lo[0] > x_lo[-1]:
        idx_lo, x_lo = idx_lo[::-1], x_lo[::-1]
    if x_up.size >= 2 and x_up[0] > x_up[-1]:
        idx_up, x_up = idx_up[::-1], x_up[::-1]
    return idx_lo, x_lo, idx_up, x_up


def _bracket(x_branch: np.ndarray, x_t: float) -> tuple[int, float, bool]:
    """Locate the x-ascending bracket [j, j+1] of ``x_branch`` containing
    ``x_t``, returning the lower index, the interpolation weight
    ``w`` (``value = (1-w)*v[j] + w*v[j+1]``), and whether ``x_t`` had to be
    clamped to a branch endpoint (fell outside ``[x_branch[0], x_branch[-1]]``).
    """
    clamped = bool(x_t < x_branch[0] or x_t > x_branch[-1])
    xt = float(np.clip(x_t, x_branch[0], x_branch[-1]))
    j = int(np.searchsorted(x_branch, xt, side="right") - 1)
    j = max(0, min(j, x_branch.size - 2))
    dx = x_branch[j + 1] - x_branch[j]
    w = (xt - x_branch[j]) / dx if dx > 1e-14 else 0.0
    return j, float(np.clip(w, 0.0, 1.0)), clamped


def stations_from_indices(
    x: np.ndarray, indices: np.ndarray, le_idx: int | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Convert panel-node indices on a given geometry's x array into (surface,
    x) pairs anchored to that geometry's OWN node positions.

    A target station used to be identified by which array slot it lived in;
    that slot's physical location drifts whenever the geometry changes (the
    inverse-design problem's whole point), which silently corrupted the
    target value once the drift exceeded a node spacing. Producers now call
    this once, at station-selection time, to freeze the physical (surface,
    x/c) location instead. ``le_idx`` (leading-edge node, ``argmin(x)`` by
    default) sets the lower/upper split, matching
    ``_split_ascending_with_nodes``.
    """
    x = np.asarray(x, dtype=float)
    indices = np.asarray(indices, dtype=int)
    if le_idx is None:
        le_idx = int(np.argmin(x))
    surface = np.where(indices <= le_idx, "lower", "upper")
    return surface, x[indices]


def interpolate_cp_at_stations(
    x_src: np.ndarray,
    cp_src: np.ndarray,
    station_surface: np.ndarray,
    station_x: np.ndarray,
) -> np.ndarray:
    """Linearly interpolate a full-loop ``(x_src, cp_src)`` curve onto
    arbitrary (surface, x) query stations, per surface (split at
    ``argmin(x_src)``, x-ascending -- same convention as ``_target_rows``).

    Producers use this to assign the prescribed target Cp value at an
    x-based station directly from the target's own curve, replacing the old
    nearest-node-index remap (which assumed the two geometries' panel grids
    stayed aligned by index -- exactly the assumption this whole change
    removes).
    """
    idx_lo, x_lo, idx_up, x_up = _split_ascending_with_nodes(np.asarray(x_src, dtype=float))
    cp_src = np.asarray(cp_src, dtype=float)
    cp_lo, cp_up = cp_src[idx_lo], cp_src[idx_up]
    station_x = np.asarray(station_x, dtype=float)
    out = np.empty(station_x.shape[0])
    for k in range(station_x.shape[0]):
        if station_surface[k] == "lower":
            out[k] = np.interp(station_x[k], x_lo, cp_lo)
        else:
            out[k] = np.interp(station_x[k], x_up, cp_up)
    return out


def _target_rows(m, station_surface: np.ndarray, station_x: np.ndarray, cp_target: np.ndarray):
    """T(U) = Cp(interpolated at (surface, x) stations) - Cp_target.

    Each station is addressed by its physical (surface, x/c) location, not a
    panel node index (module docstring). The current Cp is linearly
    interpolated between the two nodes bracketing that x on the CURRENT
    geometry's own surface (``_split_ascending_with_nodes``).

    Analytic Jacobian: ``get_cp`` is pointwise (``cp[i] = f(ue[i])``, no
    cross-node coupling) and the interpolation weight ``w`` is a function of
    node x-positions only (geometry, held fixed within one Newton
    linearization -- T_A = 0 exactly as before, see module docstring), so

        cp_i = (1-w) * cp[j] + w * cp[j+1]
        d(cp_i)/d(ue[j])   = (1-w) * cp_ue[j]
        d(cp_i)/d(ue[j+1]) =   w   * cp_ue[j+1]

    Each row therefore has TWO nonzeros (one per bracketing node's ue slot,
    index ``4*node+3``) instead of one. Falls back to the branch endpoint
    (w=0 or 1) when a station's x lies outside the current geometry's range
    on that surface; the count of stations that clamped is logged.
    """
    mod = mfoil_module()
    nsys = m.glob.Nsys
    x_all = np.asarray(m.foil.x[0], dtype=float)
    ue_all = m.glob.U[3]
    cp_all, cp_ue_all = mod.get_cp(ue_all, m.param)

    idx_lo, x_lo, idx_up, x_up = _split_ascending_with_nodes(x_all)
    branches = {"lower": (idx_lo, x_lo), "upper": (idx_up, x_up)}

    n_st = len(station_x)
    r_t = np.empty(n_st)
    t_u = sparse.lil_matrix((n_st, 4 * nsys))
    n_clamped = 0
    for k in range(n_st):
        idx_b, x_b = branches[station_surface[k]]
        j, w, clamped = _bracket(x_b, float(station_x[k]))
        n_clamped += int(clamped)
        node_j, node_j1 = int(idx_b[j]), int(idx_b[j + 1])
        cp_i = (1.0 - w) * cp_all[node_j] + w * cp_all[node_j1]
        r_t[k] = cp_i - cp_target[k]
        t_u[k, 4 * node_j + 3] += (1.0 - w) * cp_ue_all[node_j]
        t_u[k, 4 * node_j1 + 3] += w * cp_ue_all[node_j1]
    if n_clamped:
        log.info("_target_rows: %d/%d stations clamped to a branch endpoint", n_clamped, n_st)
    return r_t, t_u.tocsr()


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
    n_t, n_k = len(prob.station_x), prob.G.shape[0]
    assert_square(n_free, n_t, n_k, prob.alpha_free)
    n_alpha = 1 if prob.alpha_free else 0

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
        r_t, t_u = _target_rows(m, prob.station_surface, prob.station_x, prob.cp_target)
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

        n_total = n_flow + n_alpha + n_free
        j = sparse.lil_matrix((n_flow + n_t + n_k, n_total))
        j[:n_flow, :n_flow] = j_uu
        if prob.alpha_free:
            j[:n_flow, n_flow] = j_ualpha.reshape(-1, 1)
        j[:n_flow, n_flow + n_alpha :] = j_ua_full
        j[n_flow : n_flow + n_t, :n_flow] = t_u
        j[n_flow + n_t :, n_flow + n_alpha :] = g_free
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
        d_alpha = float(dv[n_flow]) if prob.alpha_free else 0.0
        d_a = dv[n_flow + n_alpha :]

        # --- limit + apply -------------------------------------------------
        # U block: reuse mfoil's under-relaxation machinery, then recover the ω
        # it actually applied (from the α change — α is applied as ω·dα and is
        # untouched by the post-update Hk/ctau repairs; θ-row fallback if dα≈0).
        # The SAME ω must scale the A block: under-relaxing (U, α) while stepping
        # A fully breaks the Newton direction and produces a period-2 residual
        # oscillation (observed empirically on the first T7 attempt).
        alpha_before = float(m.oper.alpha)
        u_before = m.glob.U[0].copy()
        m.glob.dU = d_u
        m.glob.dalpha = d_alpha
        mod.update_state(m)
        omega = recover_omega(
            alpha_before, float(m.oper.alpha), d_alpha, u_before, m.glob.U[0], d_u[0]
        )

        # A block: mfoil's ω, further capped by the A trust region (dossier §7.6)
        amax = float(np.max(np.abs(d_a))) if len(d_a) else 0.0
        scale = min(omega, cfg.newton.a_trust_radius / amax) if amax > 0 else omega
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
