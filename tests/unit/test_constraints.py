"""Unit tests for constraint rows (dossier §7.4). Conventions per src/cins/CLAUDE.md:
A = [A_u0..A_un, A_l0..A_ln], lower coefficients stored negative,
shared-LE row is A_u0 + A_l0 = 0."""

import numpy as np

from cins.cst.constraints import (
    area_row,
    le_radius_row,
    shared_le_radius_row,
    te_wedge_row,
)


def test_le_radius_row_selects_au0():
    n_u, n_l = 8, 8
    R_LE = 0.0155  # NACA 2412-ish
    g, b = le_radius_row(n_u, n_l, R_LE)
    assert g.shape == (n_u + n_l + 2,)
    assert np.count_nonzero(g) == 1
    assert g[0] == 1.0
    assert b == np.sqrt(2 * R_LE)


def test_le_radius_row_chord_scaling():
    g, b = le_radius_row(4, 4, R_LE=0.02, chord=2.0)
    assert b == np.sqrt(2 * 0.02 / 2.0)


def test_shared_le_radius_row_couples_blocks():
    n_u, n_l = 6, 8
    g, b = shared_le_radius_row(n_u, n_l)
    assert g.shape == (n_u + n_l + 2,)
    assert b == 0.0
    # A_u0 + A_l0 = 0 (lower stored negative)
    assert g[0] == 1.0
    assert g[n_u + 1] == 1.0
    assert np.count_nonzero(g) == 2
    # satisfied by a conventional symmetric pair
    A = np.zeros(n_u + n_l + 2)
    A[0], A[n_u + 1] = 0.35, -0.35
    assert g @ A == 0.0


def test_te_wedge_rows_select_last_coefficients():
    n_u, n_l = 8, 8
    beta = np.deg2rad(8.0)
    dz = 0.002
    g_u, b_u = te_wedge_row(n_u, n_l, beta, dz, side="upper")
    assert g_u[n_u] == 1.0 and np.count_nonzero(g_u) == 1
    assert np.isclose(b_u, np.tan(beta) + dz)
    g_l, b_l = te_wedge_row(n_u, n_l, beta, dz, side="lower")
    assert g_l[-1] == 1.0 and np.count_nonzero(g_l) == 1
    assert np.isclose(b_l, -np.tan(beta) + dz)  # sign flip — T3 review finding


def _fitted_2412(n=8):
    from cins.cst.fit import fit_cst
    from cins.solver.mfoil_adapter import make_mfoil

    m = make_mfoil(naca="2412")
    X = m.geom.xpoint
    return fit_cst(X[0], X[1], n)


def _surface_slope_at_te(A, zeta_T, h=1e-7):
    """Numerical zeta'(1) via one-sided FD on the actual surface() evaluation."""
    from cins.cst.basis import surface

    z1 = surface(np.array([1.0]), A, zeta_T)[0]
    z0 = surface(np.array([1.0 - h]), A, zeta_T)[0]
    return (z1 - z0) / h


def test_te_wedge_row_matches_fitted_airfoil_slope_both_sides():
    """Independent check (T3 adversarial-review gap): recover each surface's
    boat-tail angle from the FITTED airfoil's numerical TE slope, feed it to
    te_wedge_row, and require b to reproduce the fitted A_n coefficient.
    Exact identity used: zeta'(1) = zeta_T - A_n  (N2=1)."""
    fit = _fitted_2412()
    for side, A, zT in (
        ("upper", fit.A_upper, fit.zeta_T_upper),
        ("lower", fit.A_lower, fit.zeta_T_lower),
    ):
        slope = _surface_slope_at_te(A, zT)
        beta = np.arctan(-slope) if side == "upper" else np.arctan(slope)
        _, b = te_wedge_row(fit.n, fit.n, beta, zT, side=side)
        a_n = fit.A_upper[-1] if side == "upper" else fit.A_lower[-1]
        assert np.isclose(b, a_n, atol=5e-6), f"{side}: b={b} vs fitted A_n={a_n}"


def test_le_radius_row_consistent_with_fitted_naca2412_nose():
    """Independent check: published 4-digit nose radius r/c = 1.1019 t^2
    (0.01587 for t=0.12) must agree with the row's implied radius from the
    fitted A_u0 within a few percent (both are approximations)."""
    fit = _fitted_2412()
    r_fit = fit.A_upper[0] ** 2 / 2.0
    assert abs(r_fit - 1.1019 * 0.12**2) / (1.1019 * 0.12**2) < 0.05
    g, b = le_radius_row(fit.n, fit.n, R_LE=r_fit)
    assert np.isclose(b, fit.A_upper[0], rtol=1e-12)


def test_area_row_shape_and_te_coeff():
    n_u, n_l = 8, 6
    g, te_coeff = area_row(n_u, n_l)
    assert g.shape == (n_u + n_l + 2,)
    # upper block positive, lower block negative (area = int zeta_u - zeta_l)
    assert np.all(g[: n_u + 1] > 0)
    assert np.all(g[n_u + 1 :] < 0)
    # TE term: int psi*zeta_T dpsi = zeta_T/2 per surface, upper minus lower
    assert np.allclose(te_coeff, [0.5, -0.5])


def test_area_row_symmetric_airfoil_zero_camber_area_positive():
    """Symmetric section: A_l = -A_u; area must be 2x the upper contribution."""
    n = 8
    rng = np.random.default_rng(42)
    A_u = 0.1 + 0.2 * rng.random(n + 1)
    A = np.concatenate([A_u, -A_u])
    g, _ = area_row(n, n)
    area = g @ A
    g_half = g[: n + 1]
    assert np.isclose(area, 2 * (g_half @ A_u), rtol=1e-14)
    assert area > 0
