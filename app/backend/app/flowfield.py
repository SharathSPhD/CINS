"""Vectorized inviscid velocity-field evaluator for ``/api/flowfield``.

``vendor/mfoil/mfoil.py`` (NEVER edited: see CLAUDE.md) computes the velocity
at a single point via ``inviscid_velocity``, which itself loops over every
airfoil panel in pure Python. The old ``run_flowfield`` called that function
once per grid point, so a 60x40 grid cost ``2400 grid points * ~200 panels``
Python-level scalar evaluations -- 106.6s measured on the Render free tier,
5-12s locally, and the frontend gives up at 90s.

This module is numerically the SAME algorithm, just re-ordered: instead of
"for each point: loop over panels", it does "for each panel (order ~200):
evaluate this panel's influence on ALL grid points at once with numpy array
ops". Every contribution ``inviscid_velocity`` includes is reproduced here,
in the same order, with the same near-singular guards:

  1. N-1 linear-vortex panels (``panel_linvortex_velocity``, always called
     with ``vdir=None, onmid=False`` inside ``inviscid_velocity`` -- that is
     the only branch this module needs to replicate).
  2. The trailing-edge constant-source panel (``panel_constsource_velocity``,
     on the ``[N-1, 0]`` node pair), scaled by ``TE_info``'s ``tcp``. This is
     the one contribution the vendor guards for ``r1``/``r2`` near zero
     (``ep = 1e-9``); that guard is reproduced exactly, including its
     sequential (not independent) application of the two branches.
  3. The trailing-edge linear-vortex panel (``panel_linvortex_velocity``
     again, same node pair), scaled by ``TE_info``'s ``tdp``.
  4. The freestream term.

Correctness is enforced by ``tests/test_flowfield_vectorized.py``, which
compares this module's output point-by-point against the vendor's own
``inviscid_velocity`` to 1e-10 absolute.
"""

from __future__ import annotations

import numpy as np

# vendor panel_constsource_velocity's own r1/r2-near-zero threshold.
_EP = 1e-9


def _te_info(X: np.ndarray) -> tuple[float, float]:
    """Port of vendor ``TE_info``, trimmed to the two outputs
    ``inviscid_velocity`` actually uses (``tcp``, ``tdp``); ``hTE``/``dtdx``
    are computed by the vendor but never read there."""
    t1 = X[:, 0] - X[:, 1]
    t1 = t1 / np.linalg.norm(t1)
    t2 = X[:, -1] - X[:, -2]
    t2 = t2 / np.linalg.norm(t2)
    t = 0.5 * (t1 + t2)
    t = t / np.linalg.norm(t)
    s = X[:, -1] - X[:, 0]
    p = s / np.linalg.norm(s)
    tcp = float(abs(t[0] * p[1] - t[1] * p[0]))
    tdp = float(np.dot(t, p))
    return tcp, tdp


_PanelGeometry = tuple[
    float, float, float, float, float,  # t0, t1, n0, n1, d
    # x, z, r1, r2, theta1, theta2 (per query point)
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
]


def _panel_geometry(
    xj1: float, zj1: float, xj2: float, zj2: float, xq: np.ndarray, yq: np.ndarray
) -> _PanelGeometry:
    """Vectorized ``panel_info``: one fixed panel (``xj1,zj1``)-(``xj2,zj2``),
    many query points (``xq``, ``yq``, same shape). Returns the panel-aligned
    tangent/normal components, the panel length, and, per query point, the
    local (x, z) coordinates, r1, r2, theta1, theta2 -- identical quantities
    to the vendor's ``panel_info``, just array-valued in the query-point
    dimension instead of being called once per point."""
    dx, dz = xj2 - xj1, zj2 - zj1
    d = float(np.hypot(dx, dz))
    t0, t1 = dx / d, dz / d
    n0, n1 = -t1, t0

    xr = xq - xj1
    zr = yq - zj1
    x = xr * t0 + zr * t1
    z = xr * n0 + zr * n1

    r1 = np.hypot(x, z)
    r2 = np.hypot(x - d, z)
    theta1 = np.arctan2(z, x)
    theta2 = np.arctan2(z, x - d)
    return t0, t1, n0, n1, d, x, z, r1, r2, theta1, theta2


def _panel_linvortex_velocity_vec(
    xj1: float, zj1: float, xj2: float, zj2: float, xq: np.ndarray, yq: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized ``panel_linvortex_velocity(Xj, xi, vdir=None, onmid=False)``:
    returns ``(au, av, bu, bv)``, the (u, v) components of the ``a``, ``b``
    influence-coefficient vectors, one entry per query point. ``onmid`` is
    always ``False`` in every call ``inviscid_velocity`` makes, so that
    branch is not implemented here."""
    t0, t1, n0, n1, d, x, z, r1, r2, theta1, theta2 = _panel_geometry(xj1, zj1, xj2, zj2, xq, yq)
    dtheta = theta2 - theta1
    log_r1_r2 = np.log(r1 / r2)

    temp1 = dtheta / (2 * np.pi)
    temp2 = (2 * z * log_r1_r2 - 2 * x * dtheta) / (4 * np.pi * d)
    ug1 = temp1 + temp2
    ug2 = -temp2

    temp1 = -log_r1_r2 / (2 * np.pi)  # == log(r2/r1) / (2*pi)
    temp2 = (x * log_r1_r2 - d + z * dtheta) / (2 * np.pi * d)
    wg1 = temp1 + temp2
    wg2 = -temp2

    au = ug1 * t0 + wg1 * n0
    av = ug1 * t1 + wg1 * n1
    bu = ug2 * t0 + wg2 * n0
    bv = ug2 * t1 + wg2 * n1
    return au, av, bu, bv


def _panel_constsource_velocity_vec(
    xj1: float, zj1: float, xj2: float, zj2: float, xq: np.ndarray, yq: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized ``panel_constsource_velocity(Xj, xi, vdir=None)``, including
    the vendor's ``r1``/``r2``-near-zero guard. The vendor applies the guard
    as two SEQUENTIAL tuple assignments (the ``r2`` branch is evaluated
    second and overrides ``theta1``/``theta2`` set by the ``r1`` branch, in
    the -- practically unreachable -- case both trip at once); that ordering
    is reproduced here with two chained ``np.where`` passes rather than one
    independent pass per branch."""
    t0, t1, n0, n1, d, x, z, r1, r2, theta1, theta2 = _panel_geometry(xj1, zj1, xj2, zj2, xq, yq)

    near1 = r1 < _EP
    logr1 = np.where(near1, 0.0, np.log(np.where(near1, 1.0, r1)))
    theta1 = np.where(near1, np.pi, theta1)
    theta2 = np.where(near1, np.pi, theta2)

    near2 = r2 < _EP
    logr2 = np.where(near2, 0.0, np.log(np.where(near2, 1.0, r2)))
    theta1 = np.where(near2, 0.0, theta1)
    theta2 = np.where(near2, 0.0, theta2)

    u = (logr1 - logr2) / (2 * np.pi)
    w = (theta2 - theta1) / (2 * np.pi)
    au = u * t0 + w * n0
    av = u * t1 + w * n1
    return au, av


def inviscid_velocity_field(
    X: np.ndarray,
    gam: np.ndarray,
    Vinf: float,
    alpha_deg: float,
    xq: np.ndarray,
    yq: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized equivalent of calling vendor
    ``inviscid_velocity(X, gam, Vinf, alpha_deg, [xq[k], yq[k]], False)`` for
    every ``k``, but with ``O(n_panels)`` numpy calls instead of
    ``O(n_panels * n_points)`` Python-level scalar calls.

    Parameters
    ----------
    X : (2, N) airfoil panel node coordinates (vendor ``m.foil.x``).
    gam : (N,) vortex strengths at nodes (vendor ``m.isol.gam``).
    Vinf, alpha_deg : freestream speed and angle of attack (degrees).
    xq, yq : flat arrays of query-point coordinates, same shape.

    Returns
    -------
    (u, v) : arrays shaped like ``xq``/``yq``.
    """
    xq = np.asarray(xq, dtype=float)
    yq = np.asarray(yq, dtype=float)
    N = X.shape[1]
    u = np.zeros(xq.shape, dtype=float)
    v = np.zeros(xq.shape, dtype=float)

    for j in range(N - 1):
        xj1, zj1 = X[0, j], X[1, j]
        xj2, zj2 = X[0, j + 1], X[1, j + 1]
        au, av, bu, bv = _panel_linvortex_velocity_vec(xj1, zj1, xj2, zj2, xq, yq)
        u += au * gam[j] + bu * gam[j + 1]
        v += av * gam[j] + bv * gam[j + 1]

    # Trailing-edge panel: node N-1 -> node 0 (vendor's X[:, [N-1, 0]]).
    xj1, zj1 = X[0, N - 1], X[1, N - 1]
    xj2, zj2 = X[0, 0], X[1, 0]
    tcp, tdp = _te_info(X)

    # TE constant-source contribution.
    au, av = _panel_constsource_velocity_vec(xj1, zj1, xj2, zj2, xq, yq)
    f1u, f1v = au * (-0.5 * tcp), av * (-0.5 * tcp)
    f2u, f2v = au * (0.5 * tcp), av * (0.5 * tcp)
    u += f1u * gam[0] + f2u * gam[N - 1]
    v += f1v * gam[0] + f2v * gam[N - 1]

    # TE linear-vortex contribution.
    au, av, bu, bv = _panel_linvortex_velocity_vec(xj1, zj1, xj2, zj2, xq, yq)
    su, sv = au + bu, av + bv
    f1u, f1v = su * (0.5 * tdp), sv * (0.5 * tdp)
    f2u, f2v = su * (-0.5 * tdp), sv * (-0.5 * tdp)
    u += f1u * gam[0] + f2u * gam[N - 1]
    v += f1v * gam[0] + f2v * gam[N - 1]

    # Freestream.
    alpha_rad = np.deg2rad(alpha_deg)
    u += Vinf * np.cos(alpha_rad)
    v += Vinf * np.sin(alpha_rad)

    return u, v


def points_in_polygon(
    xq: np.ndarray, yq: np.ndarray, poly_x: np.ndarray, poly_y: np.ndarray
) -> np.ndarray:
    """Vectorized ray-casting point-in-polygon test against a closed loop
    (``poly_x``, ``poly_y``), equivalent point-by-point to the scalar
    ray-casting test this module replaces (even/odd crossing count of a
    horizontal ray to ``+x``). ``xq``/``yq`` are flat arrays; loops over
    polygon edges (order ~200), not query points, mirroring the panel loop
    above. Returns a boolean array shaped like ``xq``."""
    xq = np.asarray(xq, dtype=float)
    yq = np.asarray(yq, dtype=float)
    n = poly_x.size
    inside = np.zeros(xq.shape, dtype=bool)
    j = n - 1
    for i in range(n):
        xi, yi = poly_x[i], poly_y[i]
        xj, yj = poly_x[j], poly_y[j]
        crosses = (yi > yq) != (yj > yq)
        if np.any(crosses):
            # crosses[k] True implies yi != yj at that query point, so the
            # divide is always well-defined there; guard the elsewhere-unused
            # lanes with a dummy denom of 1 purely to avoid a spurious
            # divide-by-zero warning (their x_cross value is discarded by the
            # `crosses` mask below regardless).
            denom = np.where(crosses, yj - yi, 1.0)
            x_cross = (xj - xi) * (yq - yi) / denom + xi
            flip = crosses & (xq < x_cross)
            inside ^= flip
        j = i
    return inside
