"""The T5 geometry-update hook: push a new CST coefficient vector into a live
mfoil instance without touching the flow state.

Implements the minimal correct rebuild sequence established by T1 introspection
(docs/mfoil_internals.md §7.4): stock mfoil never changes geometry mid-Newton,
so this module provides exactly the hook the monolithic system needs. The flow
state U and the (frozen, ADR-0003) transition pattern carry over — state and
geometry march together.

Traps handled (docs/mfoil_internals.md "T5 implications"):
- stgt passed as a plain list (spline_curvature's `stgt == None` ndarray bug)
- node count N (hence Nsys) held fixed via the stgt discipline
- Istag jump detection is left to the caller/diagnostics (D-2 sanity)
"""

from __future__ import annotations

import numpy as np

from cins.cst.geometry import coords_from_A
from cins.solver.mfoil_adapter import mfoil_module


def apply_geometry(m, A_upper, A_lower, zeta_T_u, zeta_T_l, psi) -> None:
    """Rebuild all geometry-dependent operators of `m` for the given CST coefficients.

    Flow state (m.glob.U), transition flags (m.vsol.turb) and system size are
    preserved. Cost is dominated by calc_ue_m (dense O(N*Nw) + one NxN solve).
    """
    mod = mfoil_module()
    X = coords_from_A(A_upper, A_lower, zeta_T_u, zeta_T_l, psi)

    n_before = m.foil.N
    stgt = list(m.foil.s)  # LIST, not ndarray (vendor stgt==None bug)

    m.geom.npoint = X.shape[1]
    m.geom.xpoint = X
    m.geom.chord = float(X[0].max() - X[0].min())

    mod.make_panels(m, m.foil.N - 1, stgt)
    assert m.foil.N == n_before, "node count changed; Nsys invariant violated"

    mod.build_gamma(m, m.oper.alpha)
    mod.build_wake(m)
    mod.stagpoint_find(m)
    mod.identify_surfaces(m)
    mod.set_wake_gap(m)
    mod.calc_ue_m(m)


def flow_residual(m) -> np.ndarray:
    """Assemble and return the full flow residual at the current (U, geometry).

    Uses mfoil's own build_glob_sys (R: 3*Nsys rows) plus the ue-mass closure
    rows exactly as solve_glob forms them: R_ue = ue - (ueinv + ue_m @ mass(U)).
    Returns the stacked (4*Nsys,) residual so FD columns over A see every
    geometry-sensitive term (docs/mfoil_internals.md §3.2).
    """
    mod = mfoil_module()
    mod.build_glob_sys(m)
    r_visc = np.asarray(m.glob.R).ravel().copy()  # (3*Nsys,)

    # ue-mass closure rows (mirrors solve_glob's augmented block, mfoil.py)
    nsys = m.glob.Nsys
    ueinv = mod.get_ueinv(m)  # (Nsys,)
    th = m.glob.U[0]
    ds = m.glob.U[1]
    ue = m.glob.U[3]
    # mass defect mi = ue * ds ; ue = ueinv + ue_m @ mi  (sgnue handled inside ue_m)
    mi = ue * ds
    r_ue = ue - (ueinv + np.asarray(m.vsol.ue_m) @ mi)
    assert r_ue.shape == (nsys,)
    _ = th  # th unused here; kept for clarity of state layout
    return np.concatenate([r_visc, r_ue])


def dR_dA_fd(
    m,
    A_upper,
    A_lower,
    zeta_T_u,
    zeta_T_l,
    psi,
    free_idx,
    step: float,
) -> np.ndarray:
    """Central-difference ∂R/∂A over the free coefficient indices.

    ~2*len(free_idx) residual EVALUATIONS (geometry rebuild + assembly, no
    solves) — the dossier's fallback strategy, confirmed necessary by T1.
    Restores the baseline geometry before returning.

    free_idx indexes the stacked vector [A_upper, A_lower].
    """
    n_u = len(A_upper)
    A0 = np.concatenate([A_upper, A_lower]).astype(float)
    cols = []
    for j in free_idx:
        rp: list[np.ndarray] = []
        for s in (+step, -step):
            A = A0.copy()
            A[j] += s
            apply_geometry(m, A[:n_u], A[n_u:], zeta_T_u, zeta_T_l, psi)
            rp.append(flow_residual(m))
        cols.append((rp[0] - rp[1]) / (2.0 * step))
    # restore baseline geometry/operators
    apply_geometry(m, A0[:n_u], A0[n_u:], zeta_T_u, zeta_T_l, psi)
    return np.column_stack(cols) if cols else np.empty((4 * m.glob.Nsys, 0))
