"""CST basis functions — Bernstein shape functions, class function, surface.

Reference: docs/CST_MISES_Monolithic_Inverse_Design.md §3.1-3.3, §3.5-3.6.
Sign/ordering conventions are BINDING per src/cins/CLAUDE.md.

Core formulation (psi = x/c, zeta = z/c)::

    C(psi) = psi**N1 * (1-psi)**N2                    # class function
    S_i(psi) = K_i * psi**i * (1-psi)**(n-i)           # Bernstein shape fn
    zeta(psi) = C(psi) * sum_i A_i S_i(psi) + psi*zeta_T

All functions here are **complex-step safe**: no ``abs``/``max``/``min``/
comparison is applied to ``psi`` or ``A`` anywhere on the evaluation path, so
``A`` (and, for class_fn/bernstein, ``psi``) may be a complex ndarray for
complex-step differentiation without any branch changing behaviour.
"""

from __future__ import annotations

from functools import lru_cache
from math import comb

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "bernstein",
    "bernstein_matrix",
    "class_fn",
    "surface",
    "dsurface_dA",
    "le_modification",
]


def bernstein(n: int, i: int, psi: ArrayLike) -> NDArray:
    """Bernstein basis polynomial of degree n, index i: K_i psi^i (1-psi)^(n-i).

    Vectorized over ``psi`` (any shape). ``K_i = n! / (i! (n-i)!)``.
    """
    psi = np.asarray(psi)
    k_i = comb(n, i)
    return k_i * psi**i * (1.0 - psi) ** (n - i)


def bernstein_matrix(n: int, psi: ArrayLike) -> NDArray:
    """Bernstein design matrix S(psi): shape (len(psi), n+1), S[:, i] = S_i(psi)."""
    psi = np.asarray(psi)
    cols = [bernstein(n, i, psi) for i in range(n + 1)]
    return np.stack(cols, axis=-1)


def class_fn(psi: ArrayLike, N1: float = 0.5, N2: float = 1.0) -> NDArray:
    """CST class function C(psi) = psi**N1 * (1-psi)**N2.

    Default N1=0.5, N2=1.0 is the round-nose, sharp-tail family (dossier
    §3.1). Vanishes at both psi=0 and psi=1 for N1, N2 > 0.
    """
    psi = np.asarray(psi)
    return psi**N1 * (1.0 - psi) ** N2


def surface(
    psi: ArrayLike,
    A: ArrayLike,
    zeta_T: float,
    N1: float = 0.5,
    N2: float = 1.0,
) -> NDArray:
    """CST surface: zeta(psi) = C(psi) * sum_i A_i S_i(psi) + psi * zeta_T.

    ``A`` may be a complex ndarray (complex-step differentiation w.r.t. a
    coefficient); the class function and Bernstein basis depend only on the
    real grid ``psi``, so the complex part propagates linearly through the
    matrix-vector product with no branching.
    """
    psi = np.asarray(psi, dtype=float)
    A = np.asarray(A)
    n = A.shape[-1] - 1
    S = bernstein_matrix(n, psi)  # (len(psi), n+1), real
    C = class_fn(psi, N1, N2)  # (len(psi),), real
    return C * (S @ A) + psi * zeta_T


@lru_cache(maxsize=256)
def _dsurface_dA_cached(
    psi_key: tuple[float, ...], n: int, N1: float, N2: float
) -> NDArray:
    """Memoized (psi-grid, n, N1, N2) -> C(psi)[:, None] * S(psi).

    Caching strategy: ``dsurface_dA`` is design-independent (does not depend
    on A), so the Newton loop in T5/T6 calls it every iteration with an
    unchanged (psi, n, N1, N2) tuple. We key the cache on ``tuple(psi)``
    (hashable, exact float equality — the Newton loop reuses the *same*
    numpy array object each call so the values are bit-identical) plus the
    scalar shape parameters. The public ``dsurface_dA`` wrapper converts the
    incoming array to that tuple key and returns a **copy** of the cached
    matrix so callers can freely mutate their own copy without corrupting
    the cache (see test_dsurface_dA_is_cached_and_returns_independent_copies).
    """
    psi = np.array(psi_key, dtype=float)
    S = bernstein_matrix(n, psi)
    C = class_fn(psi, N1, N2)
    M = C[:, None] * S
    M.setflags(write=False)
    return M


def dsurface_dA(
    psi: ArrayLike, n: int, N1: float = 0.5, N2: float = 1.0
) -> NDArray:
    """Design-independent matrix C(psi) * S_i(psi), shape (len(psi), n+1).

    This is exactly ``d(surface)/dA`` since ``surface`` is linear in ``A``
    with ``zeta_T`` held fixed. Cached per (psi, n, N1, N2) — see
    ``_dsurface_dA_cached`` docstring for the caching strategy. Callers get
    an independent copy each call (cheap relative to matrix assembly).
    """
    psi = np.asarray(psi, dtype=float)
    key = tuple(psi.tolist())
    cached = _dsurface_dA_cached(key, int(n), float(N1), float(N2))
    return cached.copy()


def le_modification(psi: ArrayLike, a_lem: float) -> NDArray:
    """Kulfan leading-edge modification (LEM) term.

    zeta_LEM(psi) = a_lem * psi * (1 - psi)

    Chosen form and rationale (dossier §3.5, fix #1; §3.6 table cites
    Kulfan, "Modification of CST Airfoil Representation Methodology", and
    NeuralFoil's CST+LEM implementation as the reference point for this
    style of finite-nose-slope correction). The base CST term's ``psi**N1``
    factor (N1=0.5) has infinite slope at psi=0 by construction (dossier
    §3.5) — that singularity is what makes downstream Jacobian *rows* blow
    up, not the geometry itself. The additive term implemented here is a
    smooth (C^infinity, polynomial) bump that vanishes at both psi=0 and
    psi=1 like the class function does, but — unlike ``psi**0.5`` — has a
    perfectly finite, controllable slope at the leading edge:
    d(zeta_LEM)/dpsi|_{psi=0} = a_lem exactly. This is the simplest member
    of the "psi * (1-psi)**N" family referenced in the dossier; higher
    powers of (1-psi) only change the TE-ward falloff, not the LE slope,
    so N=1 is used here (documented convention choice — the exact exponent
    in Kulfan's original note is not independently reproducible from a
    paywalled source; this implementation is exact and self-consistent
    for the stated design intent, and should be revisited with an ADR if a
    primary-source formula becomes available).

    Complex-step safe: no abs/max/min/comparison on ``psi``.
    """
    psi = np.asarray(psi, dtype=float)
    return a_lem * psi * (1.0 - psi)
