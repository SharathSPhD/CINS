"""T4 — analytic linear pre-solve: initialiser + realisability gate (dossier §7.5).

This is *not* the inverse solve. It has two jobs:

1. Put the T5 Newton iteration inside its basin of attraction by producing a
   constrained-least-squares CST coefficient vector close to whatever the
   target Cp implies, cheaply (no Newton solves — just inviscid linear
   solves).
2. Flag targets that are not representable in the CST-spanned subspace
   *before* a Newton solve is attempted (the realisability metric).

**Method (dossier's pragmatic recommendation).** Build the sensitivity
matrix ``M`` (Cp response to a CST coefficient perturbation) *numerically*
from mfoil's own inviscid solve, rather than from the closed-form
thin-airfoil/Beta-function kernels (Joseph & Mohan, dossier §5.4) — a
central difference per coefficient, each perturbation costing two cheap
*inviscid* (non-Newton, single linear solve) mfoil solves. Then solve the
KKT system for the CST-constrained least-squares update.

**Station-matching problem (documented here because T5 faces the identical
issue).** mfoil re-panels any input coordinate array via
``spline_curvature`` (see docs/mfoil_internals.md §2.1) — the panel-node
x-locations it hands back therefore depend on the *local curvature* of
whatever geometry was fed in, not on the caller's psi grid. Two different
CST coefficient vectors therefore come back with two different x-station
sets. To build one consistent Cp vector per coefficient, we:

    1. Solve the *baseline* geometry (A0) once, take its mfoil panel
       x-stations as "the" station grid for this M / presolve() call.
    2. For every perturbed (or target) geometry, solve independently (its
       own re-paneling), then **interpolate its Cp back onto the baseline
       x-stations**, per surface (split at each geometry's own
       leading-edge node, found as the point of minimum panel x — the
       loop is not globally x-monotonic so a whole-loop interpolation
       would be meaningless across the LE).

This makes every column of ``M`` and every Cp vector passed to
``presolve`` directly comparable, at the cost of one linear interpolation
per perturbation (negligible next to the solve itself).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import ArrayLike, NDArray

from cins.config import CinsConfig
from cins.cst.geometry import coords_from_A
from cins.solver.mfoil_adapter import make_mfoil, mfoil_module

__all__ = [
    "InviscidCpResult",
    "SensitivityResult",
    "PresolveResult",
    "solve_inviscid_cp",
    "interpolate_cp_to_stations",
    "build_sensitivity_matrix",
    "presolve",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InviscidCpResult:
    """One inviscid mfoil solve's surface Cp, at mfoil's *own* re-paneled nodes.

    ``x``/``cp`` follow mfoil's panel-node loop order (TE-lower -> LE ->
    TE-upper, per src/cins/CLAUDE.md); ``le_idx`` is the index of the
    leading-edge node (``argmin(x)``) within that loop, needed to split the
    loop into two x-monotonic surfaces before any interpolation.
    """

    x: NDArray  # (N,) panel node x-coordinates (chords)
    cp: NDArray  # (N,) inviscid Cp at those nodes
    le_idx: int


def solve_inviscid_cp(
    A_upper: ArrayLike,
    A_lower: ArrayLike,
    zeta_T_u: float,
    zeta_T_l: float,
    psi: ArrayLike,
    cfg: CinsConfig,
) -> InviscidCpResult:
    """CST coefficients -> coords -> mfoil -> inviscid solve -> surface Cp.

    Builds a fresh headless mfoil instance from ``coords_from_A`` (via the
    adapter's ``make_mfoil(coords=...)`` path, ADR-0002) and runs
    ``solve_inviscid`` directly (not ``m.solve()``, which would branch to
    the viscous/coupled solver per ``m.oper.viscous`` — T4 only ever wants
    the cheap linear inviscid solve). ``m.post.cp`` after
    ``solve_inviscid`` is exactly the inviscid Cp (see
    docs/mfoil_internals.md §5: ``calc_force`` reads ``get_ueinv`` whenever
    ``M.oper.viscous`` is False, which ``solve_inviscid`` sets
    unconditionally).
    """
    A_upper = np.asarray(A_upper, dtype=float)
    A_lower = np.asarray(A_lower, dtype=float)
    coords = coords_from_A(
        A_upper, A_lower, zeta_T_u, zeta_T_l, psi, cfg.cst.N1, cfg.cst.N2
    )
    m = make_mfoil(coords=coords, npanel=cfg.paneling.npanel)
    m.setoper(alpha=cfg.operating.alpha_deg, Ma=cfg.operating.Ma)
    mfoil_module().solve_inviscid(m)

    x = np.array(m.foil.x[0, :], dtype=float)
    cp = np.array(m.post.cp, dtype=float)
    le_idx = int(np.argmin(x))
    return InviscidCpResult(x=x, cp=cp, le_idx=le_idx)


def _split_ascending(
    x: NDArray, cp: NDArray, le_idx: int
) -> tuple[NDArray, NDArray, NDArray, NDArray]:
    """Split a full-loop (x, cp) pair at ``le_idx`` into two x-ascending surfaces.

    Returns (x_lower_asc, cp_lower_asc, x_upper_asc, cp_upper_asc).
    """

    def _asc(xx: NDArray, cc: NDArray) -> tuple[NDArray, NDArray]:
        if xx.size >= 2 and xx[0] > xx[-1]:
            return xx[::-1], cc[::-1]
        return xx, cc

    x_lo, cp_lo = _asc(x[: le_idx + 1], cp[: le_idx + 1])
    x_up, cp_up = _asc(x[le_idx:], cp[le_idx:])
    return x_lo, cp_lo, x_up, cp_up


def interpolate_cp_to_stations(
    source: InviscidCpResult, target: InviscidCpResult
) -> NDArray:
    """Interpolate ``source``'s Cp onto ``target``'s station x-locations.

    Per-surface linear interpolation (split at each result's own LE node —
    see module docstring): the lower-surface slice of ``target`` (indices
    ``0..target.le_idx``) is filled from ``source``'s ascending lower-surface
    (x, Cp); the upper-surface slice (``target.le_idx..end``) from
    ``source``'s ascending upper-surface. Output is in ``target``'s node
    order, directly comparable to ``target.cp``.
    """
    x_lo_s, cp_lo_s, x_up_s, cp_up_s = _split_ascending(
        source.x, source.cp, source.le_idx
    )
    out = np.empty_like(target.x)
    lo = slice(0, target.le_idx + 1)
    up = slice(target.le_idx, target.x.size)
    out[lo] = np.interp(target.x[lo], x_lo_s, cp_lo_s)
    out[up] = np.interp(target.x[up], x_up_s, cp_up_s)
    return out


@dataclass(frozen=True)
class SensitivityResult:
    """Output of ``build_sensitivity_matrix``."""

    M: NDArray  # (N, n_A) — dCp/dA_k at baseline stations, central FD
    Cp0: NDArray  # (N,) baseline inviscid Cp (at baseline.x stations)
    x_stations: NDArray  # (N,) baseline mfoil panel x-coordinates
    baseline: InviscidCpResult = field(repr=False)


def build_sensitivity_matrix(
    A_upper: ArrayLike,
    A_lower: ArrayLike,
    zeta_T_u: float,
    zeta_T_l: float,
    psi: ArrayLike,
    cfg: CinsConfig,
) -> SensitivityResult:
    """Numerically build the (n_cp_stations, n_A) linearized Cp-response map.

    ``M[:, k]`` is a central difference of ``solve_inviscid_cp`` in
    coefficient ``k`` (step ``cfg.presolve.fd_step``, held fixed magnitude —
    CST coefficients are all O(0.1-1) so a single global step is
    appropriate, unlike e.g. Newton's per-iterate ``A``-scaled step).
    Coefficient ordering matches src/cins/CLAUDE.md:
    ``A = [A_u0..A_u,n_u, A_l0..A_l,n_l]`` (upper block first). Each column
    costs exactly two inviscid solves (dossier §7.5: "a few hours' work,
    exercises the same code path as the Newton coupling").

    Perturbed-geometry Cp is interpolated back onto the *baseline*
    x-stations before differencing (see module docstring) since mfoil
    re-panels every coordinate array independently.
    """
    A_upper = np.asarray(A_upper, dtype=float)
    A_lower = np.asarray(A_lower, dtype=float)
    n_u, n_l = A_upper.size, A_lower.size
    n_a = n_u + n_l
    step = cfg.presolve.fd_step

    baseline = solve_inviscid_cp(A_upper, A_lower, zeta_T_u, zeta_T_l, psi, cfg)

    M = np.zeros((baseline.x.size, n_a))
    for k in range(n_a):
        au_p, al_p = A_upper.copy(), A_lower.copy()
        au_m, al_m = A_upper.copy(), A_lower.copy()
        if k < n_u:
            au_p[k] += step
            au_m[k] -= step
        else:
            j = k - n_u
            al_p[j] += step
            al_m[j] -= step

        res_p = solve_inviscid_cp(au_p, al_p, zeta_T_u, zeta_T_l, psi, cfg)
        res_m = solve_inviscid_cp(au_m, al_m, zeta_T_u, zeta_T_l, psi, cfg)
        cp_p = interpolate_cp_to_stations(res_p, baseline)
        cp_m = interpolate_cp_to_stations(res_m, baseline)
        M[:, k] = (cp_p - cp_m) / (2.0 * step)

    logger.info(
        "build_sensitivity_matrix: n_A=%d n_stations=%d fd_step=%.3e",
        n_a,
        baseline.x.size,
        step,
    )
    return SensitivityResult(M=M, Cp0=baseline.cp, x_stations=baseline.x, baseline=baseline)


@dataclass(frozen=True)
class PresolveResult:
    """Output of ``presolve`` (dossier §7.5)."""

    A: NDArray  # (n_A,) = A0 + delta_A
    delta_A: NDArray  # (n_A,) KKT solution's coefficient block
    lam: NDArray  # (K,) Lagrange multipliers on the constraint rows
    realisability: float  # ||M @ delta_A - (Cp_target - Cp0)|| / ||Cp_target||
    realisable: bool  # realisability <= cfg.presolve.realisability_threshold
    kkt_cond: float  # condition number of the assembled KKT matrix
    sensitivity: SensitivityResult = field(repr=False)


def presolve(
    Cp_target_at_baseline_nodes: ArrayLike,
    A_upper0: ArrayLike,
    A_lower0: ArrayLike,
    zeta_T_u: float,
    zeta_T_l: float,
    psi: ArrayLike,
    constraint_rows: list[tuple[NDArray, float]],
    cfg: CinsConfig,
) -> PresolveResult:
    """Constrained-least-squares CST pre-solve (dossier §7.5).

    Linearizes Cp about the starting guess ``(A_upper0, A_lower0)`` (the
    "baseline" for ``build_sensitivity_matrix``'s finite differences —
    *not* necessarily the eventual answer): ``Cp(A) ~= Cp0 + M @ (A - A0)``.
    Solves the KKT system for the constrained least-squares step
    ``delta_A``::

        [ MtM   Gt ] [ delta_A ]   [ Mt @ (Cp_target - Cp0) ]
        [ G     0  ] [ lam     ] = [ b - G @ A0             ]

    where ``(G, b)`` is the stacked-row form of ``constraint_rows`` (each a
    ``(g, b)`` pair from ``cst/constraints.py``, ``g @ A = b``). With no
    constraint rows this collapses to the plain normal equations
    ``MtM @ delta_A = Mt @ (Cp_target - Cp0)``.

    ``Cp_target_at_baseline_nodes`` must already be expressed at the
    baseline's own mfoil panel x-stations (``build_sensitivity_matrix``'s
    ``x_stations`` for this same ``(A_upper0, A_lower0, ...)``) — callers
    targeting a different geometry's Cp must interpolate it there first,
    e.g. with ``solve_inviscid_cp`` + ``interpolate_cp_to_stations`` (the
    same station-matching machinery used internally).

    **Realisability metric.** The dossier states it as
    ``||M @ A* - Cp_target|| / ||Cp_target||`` for a linear map ``Cp = M @ A``.
    Here ``M`` is a *local* sensitivity (a Jacobian about ``A0``, not a full
    linear operator — Cp0 is a nonlinear baseline solve), so the equivalent
    quantity is the predicted-vs-target residual of the *linear model
    actually solved*: ``predicted_Cp = Cp0 + M @ delta_A``, giving
    ``residual = M @ delta_A - (Cp_target - Cp0)``. This is exactly the KKT
    system's top-block residual and reduces to the dossier's expression
    when ``Cp0`` is itself already very close to ``Cp_target`` (the regime
    the metric is meant to gate). Norm choice: Euclidean (L2) over Cp
    stations for both numerator and denominator, consistent with the
    least-squares objective being solved.
    """
    sens = build_sensitivity_matrix(A_upper0, A_lower0, zeta_T_u, zeta_T_l, psi, cfg)
    M = sens.M
    Cp0 = sens.Cp0
    Cp_target = np.asarray(Cp_target_at_baseline_nodes, dtype=float)
    delta_target = Cp_target - Cp0

    A0 = np.concatenate([np.asarray(A_upper0, dtype=float), np.asarray(A_lower0, dtype=float)])
    n_a = A0.size

    if constraint_rows:
        G = np.stack([np.asarray(g, dtype=float) for g, _ in constraint_rows])
        b = np.array([float(bi) for _, bi in constraint_rows])
    else:
        G = np.zeros((0, n_a))
        b = np.zeros(0)
    k = G.shape[0]

    MtM = M.T @ M
    kkt = np.zeros((n_a + k, n_a + k))
    kkt[:n_a, :n_a] = MtM
    kkt[:n_a, n_a:] = G.T
    kkt[n_a:, :n_a] = G
    rhs = np.concatenate([M.T @ delta_target, b - G @ A0])

    kkt_cond = float(np.linalg.cond(kkt))
    sol = np.linalg.solve(kkt, rhs)
    delta_A = sol[:n_a]
    lam = sol[n_a:]
    A = A0 + delta_A

    resid = M @ delta_A - delta_target
    target_norm = float(np.linalg.norm(Cp_target))
    realisability = float(np.linalg.norm(resid) / target_norm) if target_norm > 0 else float("inf")
    realisable = realisability <= cfg.presolve.realisability_threshold

    logger.info(
        "presolve: n_A=%d n_constraints=%d realisability=%.4f (threshold %.4f) "
        "kkt_cond=%.3e realisable=%s",
        n_a,
        k,
        realisability,
        cfg.presolve.realisability_threshold,
        kkt_cond,
        realisable,
    )

    return PresolveResult(
        A=A,
        delta_A=delta_A,
        lam=lam,
        realisability=realisability,
        realisable=realisable,
        kkt_cond=kkt_cond,
        sensitivity=sens,
    )
