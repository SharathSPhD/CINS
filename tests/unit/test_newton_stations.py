"""Unit tests for the x-based target-station machinery (2026-08-05 fix):

A target station used to be identified by a panel-node INDEX. When the
geometry changes -- the ordinary case during a Newton iteration, or between
two different starting shapes -- the node at that index moves to a different
physical location, silently corrupting the target it was supposed to carry.
This module tests the replacement: a station identified by its physical
(surface, x/c) location, with the current Cp there found by interpolating
between the two panel nodes that currently bracket it on that surface
(``cins.solver.newton._target_rows``, ``stations_from_indices``,
``interpolate_cp_at_stations``).

Covers:
- exactness at the SAME geometry (interpolated == nodal, ~1e-12);
- a station keeping its physical position across two DIFFERENT geometries,
  where the old node-index scheme would not;
- the analytic Jacobian rows (the two-nonzero-per-row bracket structure)
  against a central finite difference of the target residual w.r.t. U.
"""

from __future__ import annotations

import numpy as np

from cins.config import load_config
from cins.solver.mfoil_adapter import make_mfoil
from cins.solver.newton import (
    _bracket,
    _split_ascending_with_nodes,
    _target_rows,
    interpolate_cp_at_stations,
    stations_from_indices,
)

CFG = load_config()


def _natural_solve(naca: str):
    m = make_mfoil(naca=naca, npanel=CFG.paneling.npanel)
    m.setoper(alpha=CFG.operating.alpha_deg, Re=CFG.operating.Re)
    m.solve()
    assert m.glob.conv, f"NACA {naca} natural solve did not converge"
    return m


# --------------------------------------------------------------------------- #
# Exactness at the same geometry
# --------------------------------------------------------------------------- #


def test_interpolation_matches_nodal_values_at_same_geometry():
    """Querying a station AT an existing node's own x should reproduce that
    node's Cp to ~1e-12 (the interpolation is exact where the two agree)."""
    m = _natural_solve("2412")
    x = np.asarray(m.foil.x[0], dtype=float)
    cp = np.asarray(m.post.cp, dtype=float)[: m.foil.N]
    n_foil = m.foil.N

    idx = np.unique(np.linspace(3, n_foil - 4, 25).astype(int))
    surf, xs = stations_from_indices(x, idx)

    cp_interp = interpolate_cp_at_stations(x, cp, surf, xs)
    max_dev = float(np.max(np.abs(cp_interp - cp[idx])))
    assert max_dev < 1e-12, f"interpolated-vs-nodal Cp deviation {max_dev:.3e} too large"

    # The target residual itself must also vanish to the same precision when
    # the prescribed target is exactly the current nodal Cp.
    r_t, _ = _target_rows(m, surf, xs, cp[idx])
    max_r = float(np.max(np.abs(r_t)))
    assert max_r < 1e-12, f"target residual {max_r:.3e} should vanish at the same geometry"


# --------------------------------------------------------------------------- #
# Physical position survives a geometry change; a node index does not
# --------------------------------------------------------------------------- #


def test_x_based_station_keeps_physical_position_while_node_index_does_not():
    """On a geometry that differs substantially from the one a station was
    selected on, addressing it by panel-node index silently jumps to a
    different physical location; addressing it by (surface, x/c) does not."""
    m1 = _natural_solve("2412")
    m2 = _natural_solve("0012")  # a deliberately different geometry/paneling

    n_foil = min(m1.foil.N, m2.foil.N)
    i = n_foil // 3  # an interior node, well clear of LE/TE
    x1 = np.asarray(m1.foil.x[0], dtype=float)
    x2 = np.asarray(m2.foil.x[0], dtype=float)

    surf_arr, x_arr = stations_from_indices(x1, np.array([i]))
    surf, x_t = surf_arr[0], float(x_arr[0])

    # The OLD (broken) scheme: same slot, different geometry.
    x_by_index_on_m2 = float(x2[i])
    node_index_drift = abs(x_by_index_on_m2 - x_t)
    assert node_index_drift > 1e-3, (
        f"expected a measurable node-index drift between geometries, got {node_index_drift:.3e}"
    )

    # The x-based station's physical value is unaffected by construction --
    # it is just the float x_t -- and the bracket search on m2's OWN geometry
    # genuinely straddles that x, i.e. it addresses the same physical point.
    idx_lo, x_lo, idx_up, x_up = _split_ascending_with_nodes(x2)
    x_branch = x_lo if surf == "lower" else x_up
    j, w, clamped = _bracket(x_branch, x_t)
    assert not clamped, "station should fall inside m2's surface range"
    assert x_branch[j] - 1e-12 <= x_t <= x_branch[j + 1] + 1e-12, (
        "bracket on the new geometry must straddle the station's physical x"
    )
    assert 0.0 <= w <= 1.0


# --------------------------------------------------------------------------- #
# Analytic Jacobian vs central FD
# --------------------------------------------------------------------------- #


def test_target_rows_jacobian_matches_central_fd():
    """d(target residual)/d(U), assembled analytically in _target_rows, must
    match a central finite difference over every component of every node's
    state (th, ds, sa, ue) -- reports the max relative deviation, the
    correctness gate for the two-nonzero-per-row bracket Jacobian."""
    m = _natural_solve("2412")
    nsys = m.glob.Nsys
    n_foil = m.foil.N
    x_all = np.asarray(m.foil.x[0], dtype=float)

    idx = np.unique(np.linspace(8, n_foil - 9, 10).astype(int))
    surf, xs = stations_from_indices(x_all, idx)
    # Offset off the exact node x's so the bracket weights are interior
    # (0 < w < 1) rather than degenerate 0/1 -- a strictly harder test of the
    # two-nonzero row structure than querying exactly at a node.
    xs = xs + 3e-4
    cp_target = np.zeros(len(xs))

    _, t_u = _target_rows(m, surf, xs, cp_target)
    t_u_dense = np.asarray(t_u.todense())

    U0 = m.glob.U.copy()
    eps = 1e-6
    max_rel = 0.0
    max_abs_where_zero = 0.0
    for node in range(nsys):
        for comp in range(4):
            col = 4 * node + comp
            analytic_col = t_u_dense[:, col]

            m.glob.U = U0.copy()
            m.glob.U[comp, node] += eps
            rp, _ = _target_rows(m, surf, xs, cp_target)

            m.glob.U = U0.copy()
            m.glob.U[comp, node] -= eps
            rm, _ = _target_rows(m, surf, xs, cp_target)

            fd_col = (rp - rm) / (2.0 * eps)
            denom = np.maximum(np.abs(analytic_col), np.abs(fd_col))
            mask = denom > 1e-8
            if mask.any():
                rel = np.abs(fd_col[mask] - analytic_col[mask]) / denom[mask]
                max_rel = max(max_rel, float(rel.max()))
            else:
                max_abs_where_zero = max(max_abs_where_zero, float(np.max(np.abs(fd_col))))
    m.glob.U = U0.copy()

    print(
        f"_target_rows Jacobian FD check: max relative deviation={max_rel:.3e}, "
        f"max FD leakage where analytic=0 is {max_abs_where_zero:.3e}"
    )
    assert max_rel < 1e-5, f"analytic vs FD Jacobian max relative deviation {max_rel:.3e}"
    assert max_abs_where_zero < 1e-6, (
        f"FD found nonzero sensitivity {max_abs_where_zero:.3e} where the analytic row is zero "
        "(th/ds/sa components, or a non-bracketing node's ue)"
    )
