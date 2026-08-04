"""Least-squares CST fit to given airfoil coordinates (dossier §7.3).

Splits the input point loop into upper/lower surfaces at the leading edge
(the point of minimum x), normalizes to unit chord, and solves a linear
least-squares problem for the Bernstein coefficients on each surface using
the design-independent matrix from ``cins.cst.basis.dsurface_dA``.

Handles both orderings seen in practice:
  - mfoil CCW: TE-lower -> LE -> TE-upper
  - Selig .dat: TE -> upper -> LE -> lower -> TE
because the split-at-LE-index + per-surface psi-ascending sort does not
depend on which direction the loop runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from cins.cst.basis import dsurface_dA

__all__ = ["FitResult", "fit_cst"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FitResult:
    """Result of a least-squares CST fit.

    Lower-surface coefficients (``A_lower``) come out with their natural
    (negative) sign per the BINDING convention in src/cins/CLAUDE.md — no
    sign is forced; a conventional airfoil's lower surface simply fits
    negative given standard (x, y) data.
    """

    A_upper: NDArray  # (n+1,)
    A_lower: NDArray  # (n+1,)
    zeta_T_upper: float
    zeta_T_lower: float
    n: int
    N1: float
    N2: float
    rms: float  # combined RMS residual, in chords
    gram_condition: float  # max(cond(M_u^T M_u), cond(M_l^T M_l))


def _split_surfaces(
    x: NDArray, y: NDArray
) -> tuple[NDArray, NDArray, NDArray, NDArray, float, float]:
    """Normalize chord and split the point loop into (psi, zeta) per surface,
    each sorted psi ascending from 0 (LE) to 1 (TE). Direction-agnostic."""
    x0 = float(x.min())
    chord = float(x.max() - x0)
    psi_all = (x - x0) / chord
    zeta_all = y / chord

    le_idx = int(np.argmin(x))
    seg1_psi, seg1_zeta = psi_all[: le_idx + 1], zeta_all[: le_idx + 1]
    seg2_psi, seg2_zeta = psi_all[le_idx:], zeta_all[le_idx:]

    def _ascending(p: NDArray, z: NDArray) -> tuple[NDArray, NDArray]:
        if p.size >= 2 and p[0] > p[-1]:
            return p[::-1], z[::-1]
        return p, z

    seg1_psi, seg1_zeta = _ascending(seg1_psi, seg1_zeta)
    seg2_psi, seg2_zeta = _ascending(seg2_psi, seg2_zeta)

    # whichever segment sits higher (mean zeta) is the upper surface
    if np.mean(seg1_zeta) >= np.mean(seg2_zeta):
        psi_u, zeta_u, psi_l, zeta_l = seg1_psi, seg1_zeta, seg2_psi, seg2_zeta
    else:
        psi_u, zeta_u, psi_l, zeta_l = seg2_psi, seg2_zeta, seg1_psi, seg1_zeta

    return psi_u, zeta_u, psi_l, zeta_l, chord, x0


def _fit_one_surface(
    psi: NDArray, zeta: NDArray, n: int, N1: float, N2: float, zeta_T: float | None
) -> tuple[NDArray, float, NDArray]:
    """Solve zeta = C(psi)*S(psi)@A + psi*zeta_T for A by linear least squares.

    Returns (A, zeta_T_used, design_matrix M) where M = dsurface_dA(psi, n).
    """
    if zeta_T is None:
        # zeta(psi=1) = zeta_T exactly (C(1)=0 for N2>0, see basis.surface
        # endpoint identity), so read it directly off the TE-most data point.
        te_order = np.argsort(psi)
        zeta_T = float(zeta[te_order[-1]])

    M = dsurface_dA(psi, n, N1, N2)  # (npts, n+1), design-independent
    rhs = zeta - psi * zeta_T
    A, *_ = np.linalg.lstsq(M, rhs, rcond=None)
    return A, zeta_T, M


def fit_cst(
    x: ArrayLike,
    y: ArrayLike,
    n: int,
    N1: float = 0.5,
    N2: float = 1.0,
    te_gap: float | None = None,
) -> FitResult:
    """Least-squares CST fit to airfoil coordinates (x, y), any chord/units.

    Args:
        x, y: 1-D coordinate arrays, either mfoil CCW or Selig ordering.
        n: Bernstein order per side (same n used for both surfaces here).
        N1, N2: class-function exponents (dossier default 0.5, 1.0).
        te_gap: if given, overrides the TE closure: zeta_T,u = +te_gap/2,
            zeta_T,l = -te_gap/2 (BINDING convention, src/cins/CLAUDE.md).
            If None, zeta_T is read directly from each surface's TE data
            point (exact endpoint identity, see ``_fit_one_surface``).

    Returns:
        FitResult with A_upper, A_lower (natural sign), zeta_T values, RMS
        residual (in chords), and gram_condition (Gram-matrix conditioning,
        the empirical FM-2 evidence per dossier §7.3).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    psi_u, zeta_u, psi_l, zeta_l, chord, x0 = _split_surfaces(x, y)

    zt_u = te_gap / 2 if te_gap is not None else None
    zt_l = -te_gap / 2 if te_gap is not None else None

    A_upper, zeta_T_upper, M_u = _fit_one_surface(psi_u, zeta_u, n, N1, N2, zt_u)
    A_lower, zeta_T_lower, M_l = _fit_one_surface(psi_l, zeta_l, n, N1, N2, zt_l)

    resid_u = M_u @ A_upper + psi_u * zeta_T_upper - zeta_u
    resid_l = M_l @ A_lower + psi_l * zeta_T_lower - zeta_l
    resid = np.concatenate([resid_u, resid_l])
    rms = float(np.sqrt(np.mean(resid**2)))

    cond_u = float(np.linalg.cond(M_u.T @ M_u))
    cond_l = float(np.linalg.cond(M_l.T @ M_l))
    gram_condition = max(cond_u, cond_l)

    logger.info(
        "fit_cst: n=%d N1=%.3f N2=%.3f rms=%.3e cond(GtG)=%.3e chord=%.6f x0=%.6f",
        n,
        N1,
        N2,
        rms,
        gram_condition,
        chord,
        x0,
    )

    return FitResult(
        A_upper=A_upper,
        A_lower=A_lower,
        zeta_T_upper=zeta_T_upper,
        zeta_T_lower=zeta_T_lower,
        n=n,
        N1=N1,
        N2=N2,
        rms=rms,
        gram_condition=gram_condition,
    )
