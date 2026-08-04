"""CST -> panel-node geometry (dossier §7.3).

Node ordering (src/cins/CLAUDE.md, BINDING): TE lower -> LE -> TE upper,
counterclockwise, LE point shared once (psi=0 appears exactly once). This
mirrors mfoil's own ``naca_points`` construction (vendor/mfoil/mfoil.py):
``xs = concat(flip(x), x[1:])`` — TE-lower..LE then LE+1..TE-upper.
"""

from __future__ import annotations

import logging

import numpy as np
from numpy.typing import ArrayLike, NDArray

from cins.cst.basis import surface

__all__ = ["cosine_spacing", "coords_from_A"]

logger = logging.getLogger(__name__)


def cosine_spacing(npoint: int) -> NDArray:
    """Cosine-clustered psi grid on [0, 1], clustering at both LE and TE.

    psi_k = 0.5 * (1 - cos(theta_k)),  theta_k = k*pi/(npoint-1), k=0..npoint-1

    d(psi)/d(theta) = 0.5*sin(theta) -> 0 at theta=0 and theta=pi, i.e. point
    density is highest at psi=0 (LE) and psi=1 (TE) — matters for FM-3
    (dossier §4, §7.3): the LE-singular Jacobian rows need resolution there.
    """
    theta = np.linspace(0.0, np.pi, int(npoint))
    return 0.5 * (1.0 - np.cos(theta))


def coords_from_A(
    A_upper: ArrayLike,
    A_lower: ArrayLike,
    zeta_T_u: float,
    zeta_T_l: float,
    psi: ArrayLike,
    N1: float = 0.5,
    N2: float = 1.0,
) -> NDArray:
    """CST coefficients -> (2, N) node array in mfoil's expected ordering.

    Ordering: TE lower -> LE -> TE upper, counterclockwise, LE point (psi=0)
    appears exactly once (BINDING, src/cins/CLAUDE.md). ``psi`` must be an
    ascending grid with psi[0]=0, psi[-1]=1 (e.g. ``cosine_spacing``).

    Lower-surface coefficients ``A_lower`` are expected in their natural
    (negative) sign per the BINDING convention; ``surface()`` does not care
    about sign, it just evaluates C(psi)*sum_i A_i S_i(psi) + psi*zeta_T.

    Output shape: (2, 2*len(psi) - 1) — len(psi) lower-branch points
    (TE..LE) plus len(psi)-1 upper-branch points (LE+1..TE), the LE point
    not duplicated.
    """
    psi = np.asarray(psi, dtype=float)
    A_upper = np.asarray(A_upper, dtype=float)
    A_lower = np.asarray(A_lower, dtype=float)

    z_upper = surface(psi, A_upper, zeta_T_u, N1, N2)  # (len(psi),)
    z_lower = surface(psi, A_lower, zeta_T_l, N1, N2)  # (len(psi),)

    x = np.concatenate([psi[::-1], psi[1:]])  # (2*len(psi)-1,)
    z = np.concatenate([z_lower[::-1], z_upper[1:]])  # (2*len(psi)-1,)

    logger.debug(
        "coords_from_A: n_upper=%d n_lower=%d npoint_out=%d",
        A_upper.size - 1,
        A_lower.size - 1,
        x.size,
    )
    return np.vstack([x, z])  # (2, N)
