"""Correctness gate for app.flowfield's vectorized inviscid-velocity
evaluator (app/backend/app/flowfield.py): the whole point of vectorizing is
speed, and speed is worthless if the numbers are wrong, so this is the gate
that must pass before the vectorized path is trusted.

Compares, point by point, against the vendor's own scalar
``inviscid_velocity`` (vendor/mfoil/mfoil.py, never edited: see CLAUDE.md)
on a real solved airfoil (NACA 2412), across a random sample spanning the
flowfield domain PLUS points close to the surface (where the panel-relative
geometry is least forgiving of an algebra slip). Tolerance is 1e-10
absolute, matching the task's correctness bar; if it doesn't match, the fix
belongs in app/flowfield.py, not in a loosened tolerance.
"""

from __future__ import annotations

import numpy as np
import pytest
from app.engine import _point_in_polygon
from app.flowfield import inviscid_velocity_field, points_in_polygon

from cins.solver.mfoil_adapter import make_mfoil, mfoil_module


def _solved_naca2412(alpha: float = 4.0):
    m = make_mfoil(naca="2412")
    m.setoper(alpha=alpha, Ma=0.0)
    mod = mfoil_module()
    mod.solve_inviscid(m)
    return m, mod


def _sample_points(m, rng: np.random.Generator, n_random: int, n_near_surface: int):
    """n_random points spread across the default flowfield domain, plus
    n_near_surface points offset a small random distance along the airfoil's
    surface normal (both just outside and just inside the body) -- the
    "close to the surface" case the task calls out, where r1/r2 for the
    nearest panel(s) are small but never exactly zero."""
    x_random = rng.uniform(-0.5, 1.5, n_random)
    y_random = rng.uniform(-0.6, 0.6, n_random)

    X = np.asarray(m.foil.x, dtype=float)  # (2, N)
    N = X.shape[1]
    idx = rng.integers(0, N - 1, n_near_surface)  # panel start node
    p1 = X[:, idx]
    p2 = X[:, idx + 1]
    seg = p2 - p1
    seg_len = np.hypot(seg[0], seg[1])
    seg_len[seg_len == 0] = 1.0
    t_hat = seg / seg_len
    n_hat = np.stack([-t_hat[1], t_hat[0]])  # panel normal
    frac = rng.uniform(0.0, 1.0, n_near_surface)
    base = p1 + seg * frac
    # signed offset in [-1e-2, -1e-4] U [1e-4, 1e-2] chord: close to the
    # surface on both sides, never coincident with a node or panel line.
    mag = rng.uniform(1e-4, 1e-2, n_near_surface)
    sign = rng.choice([-1.0, 1.0], n_near_surface)
    offset = base + n_hat * (mag * sign)

    x_all = np.concatenate([x_random, offset[0]])
    y_all = np.concatenate([y_random, offset[1]])
    return x_all, y_all


def test_vectorized_matches_vendor_inviscid_velocity():
    m, mod = _solved_naca2412(alpha=4.0)
    X = np.asarray(m.foil.x, dtype=float)
    gam = np.asarray(m.isol.gam, dtype=float)
    Vinf = float(m.param.Vinf)
    alpha = float(m.oper.alpha)

    rng = np.random.default_rng(20260805)
    xq, yq = _sample_points(m, rng, n_random=150, n_near_surface=60)
    assert xq.size >= 200

    u_vec, v_vec = inviscid_velocity_field(X, gam, Vinf, alpha, xq, yq)
    assert u_vec.shape == xq.shape
    assert np.all(np.isfinite(u_vec))
    assert np.all(np.isfinite(v_vec))

    u_ref = np.empty_like(xq)
    v_ref = np.empty_like(xq)
    for k in range(xq.size):
        vel = mod.inviscid_velocity(X, gam, Vinf, alpha, np.array([xq[k], yq[k]]), False)
        u_ref[k] = vel[0]
        v_ref[k] = vel[1]

    max_dev_u = float(np.max(np.abs(u_vec - u_ref)))
    max_dev_v = float(np.max(np.abs(v_vec - v_ref)))
    assert max_dev_u < 1e-10, f"u deviates from vendor by {max_dev_u:.3e}"
    assert max_dev_v < 1e-10, f"v deviates from vendor by {max_dev_v:.3e}"


def test_vectorized_matches_vendor_at_other_alpha():
    """Same equality gate at a different angle of attack, so a coincidental
    match at alpha=4 alone can't hide a sign error that only shows up once
    the freestream direction changes."""
    m, mod = _solved_naca2412(alpha=-6.0)
    X = np.asarray(m.foil.x, dtype=float)
    gam = np.asarray(m.isol.gam, dtype=float)
    Vinf = float(m.param.Vinf)
    alpha = float(m.oper.alpha)

    rng = np.random.default_rng(7)
    xq, yq = _sample_points(m, rng, n_random=120, n_near_surface=80)

    u_vec, v_vec = inviscid_velocity_field(X, gam, Vinf, alpha, xq, yq)
    u_ref = np.empty_like(xq)
    v_ref = np.empty_like(xq)
    for k in range(xq.size):
        vel = mod.inviscid_velocity(X, gam, Vinf, alpha, np.array([xq[k], yq[k]]), False)
        u_ref[k] = vel[0]
        v_ref[k] = vel[1]

    assert float(np.max(np.abs(u_vec - u_ref))) < 1e-10
    assert float(np.max(np.abs(v_vec - v_ref))) < 1e-10


def test_points_in_polygon_masks_identically_to_scalar():
    """The vectorized ray-casting mask (app.flowfield.points_in_polygon) must
    flag exactly the same points as the existing scalar
    app.engine._point_in_polygon it replaces -- including at least one point
    that IS inside the body, so the "inside is masked" behavior is actually
    exercised, not just vacuously true."""
    m, _ = _solved_naca2412(alpha=4.0)
    X = np.asarray(m.foil.x, dtype=float)
    poly_x, poly_y = X[0], X[1]

    rng = np.random.default_rng(4242)
    xq = rng.uniform(-0.5, 1.5, 300)
    yq = rng.uniform(-0.6, 0.6, 300)
    # force some clearly-interior points (mid-chord, near y=0, well inside a
    # 12%-thick section) so the "inside" branch is genuinely covered.
    xq = np.concatenate([xq, np.full(20, 0.4)])
    yq = np.concatenate([yq, np.zeros(20)])

    vec_mask = points_in_polygon(xq, yq, poly_x, poly_y)
    scalar_mask = np.array(
        [_point_in_polygon(float(x), float(y), poly_x, poly_y) for x, y in zip(xq, yq)]
    )

    assert vec_mask.dtype == np.bool_
    assert np.array_equal(vec_mask, scalar_mask)
    assert vec_mask.any(), "expected at least one point to be inside the body"
    assert not vec_mask.all()


@pytest.mark.parametrize("alpha", [0.0, 8.0])
def test_vectorized_matches_vendor_grid_shaped(alpha):
    """Exercise the actual call shape run_flowfield uses: a full nx*ny grid,
    flattened, including points that fall inside the airfoil body (still a
    well-defined analytic velocity there, just masked out downstream)."""
    m, mod = _solved_naca2412(alpha=alpha)
    X = np.asarray(m.foil.x, dtype=float)
    gam = np.asarray(m.isol.gam, dtype=float)
    Vinf = float(m.param.Vinf)
    alpha_actual = float(m.oper.alpha)

    xs = np.linspace(-0.5, 1.5, 24)
    ys = np.linspace(-0.6, 0.6, 16)
    xg, yg = np.meshgrid(xs, ys)
    xq, yq = xg.ravel(), yg.ravel()

    u_vec, v_vec = inviscid_velocity_field(X, gam, Vinf, alpha_actual, xq, yq)

    u_ref = np.empty_like(xq)
    v_ref = np.empty_like(xq)
    for k in range(xq.size):
        vel = mod.inviscid_velocity(X, gam, Vinf, alpha_actual, np.array([xq[k], yq[k]]), False)
        u_ref[k] = vel[0]
        v_ref[k] = vel[1]

    assert float(np.max(np.abs(u_vec - u_ref))) < 1e-10
    assert float(np.max(np.abs(v_vec - v_ref))) < 1e-10
