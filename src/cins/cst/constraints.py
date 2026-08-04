"""Geometric constraint functionals as linear rows (dossier §3.2–§3.4, §7.4).

Each function returns a row vector g over the stacked coefficient vector
A = [A_u0..A_u,n_u, A_l0..A_l,n_l]  (upper block first, lower stored negative;
see src/cins/CLAUDE.md) and the right-hand side b, such that  g · A = b.

These rows are what convert constrained shape *optimization* into constrained
*root-finding*: under CST every quantity below is exactly linear in A, with
closed-form coefficients — no quadrature, no predicates (dossier §1.5).
Numerical quadrature appears only in tests as the independent check.
"""

from __future__ import annotations

from math import comb

import numpy as np
from numpy.typing import NDArray
from scipy.special import beta as _beta_fn


def _n_a(n_upper: int, n_lower: int) -> int:
    return n_upper + n_lower + 2


def le_radius_row(
    n_upper: int, n_lower: int, R_LE: float, chord: float = 1.0
) -> tuple[NDArray, float]:
    """A_u0 = sqrt(2 R_LE / c)  (dossier §3.2; osculating parabola R_LE = A0^2/2).

    Single nonzero entry on the first upper coefficient.
    """
    g = np.zeros(_n_a(n_upper, n_lower))
    g[0] = 1.0
    return g, float(np.sqrt(2.0 * R_LE / chord))


def shared_le_radius_row(n_upper: int, n_lower: int) -> tuple[NDArray, float]:
    """A_u0 + A_l0 = 0 — equal LE radius magnitude on both surfaces.

    Lower coefficients are stored negative, so |A_l0| = -A_l0 and the dossier's
    A_u0 - |A_l0| = 0 becomes A_u0 + A_l0 = 0. Equivalent to G2 curvature
    continuity at the nose (dossier §3.3).
    """
    g = np.zeros(_n_a(n_upper, n_lower))
    g[0] = 1.0
    g[n_upper + 1] = 1.0
    return g, 0.0


def te_wedge_row(
    n_upper: int,
    n_lower: int,
    beta: float,
    dz_TE: float,
    side: str = "upper",
    chord: float = 1.0,
) -> tuple[NDArray, float]:
    """TE wedge row from the exact identity  ζ'(1) = ζ_T − A_n  (N2 = 1).

    With the boat-tail half-angle defined per surface as the wedge closing angle
    (upper surface descends toward the TE: tan β_u = −ζ_u'(1); lower surface
    rises: tan β_l = +ζ_l'(1)), the identity gives
        upper:  A_u,n = ζ_T,u/c + tan β_u
        lower:  A_l,n = ζ_T,l/c − tan β_l      (sign flip — adversarial review
                 T3 finding, verified against fitted NACA 2412 TE slope)
    beta in radians; dz_TE is the surface's signed TE offset.
    """
    g = np.zeros(_n_a(n_upper, n_lower))
    if side == "upper":
        g[n_upper] = 1.0
        b = np.tan(beta) + dz_TE / chord
    elif side == "lower":
        g[n_upper + 1 + n_lower] = 1.0
        b = -np.tan(beta) + dz_TE / chord
    else:
        raise ValueError(f"side must be 'upper' or 'lower', got {side!r}")
    return g, float(b)


def area_row(
    n_upper: int, n_lower: int, N1: float = 0.5, N2: float = 1.0
) -> tuple[NDArray, NDArray]:
    """Inscribed area as a linear functional of A (dossier §3.4).

    area = ∫ (ζ_u − ζ_l) dψ
         = Σ_i A_u,i K_i B(i+N1+1, n_u−i+N2+1)  −  Σ_i A_l,i K_i B(i+N1+1, n_l−i+N2+1)
           + (ζ_T,u − ζ_T,l)/2

    Returns (g, te_coeff): g over the stacked A vector (upper block positive,
    lower negative — subtracting a negatively-stored lower surface adds area),
    and te_coeff = [+1/2, −1/2] multiplying [ζ_T,u, ζ_T,l].

    Usage as an equality row for target area 'S':
        g · A = S − te_coeff · [ζ_T,u, ζ_T,l]
    """
    g = np.zeros(_n_a(n_upper, n_lower))
    for i in range(n_upper + 1):
        g[i] = comb(n_upper, i) * _beta_fn(i + N1 + 1.0, n_upper - i + N2 + 1.0)
    for i in range(n_lower + 1):
        g[n_upper + 1 + i] = -comb(n_lower, i) * _beta_fn(i + N1 + 1.0, n_lower - i + N2 + 1.0)
    te_coeff = np.array([0.5, -0.5])
    return g, te_coeff


def curvature_derivative_continuity_row(n_upper: int, n_lower: int) -> tuple[NDArray, float]:
    """G3 continuity row (involves A_u1, A_l1 — dossier §3.3). Optional for Stage 1.

    Deliberately unimplemented until derived and numerically verified; raising is
    safer than shipping an unverified sign convention into the Newton system.
    """
    raise NotImplementedError(
        "G3 row not yet derived/verified; not required for Stage 1 gates (dossier: optional)"
    )
