"""Unit tests for cins.cst.fit (dossier §7.3)."""

from __future__ import annotations

import numpy as np

from cins.cst.fit import FitResult, fit_cst
from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.solver.mfoil_adapter import make_mfoil


def _synthetic_airfoil(n=8, npoint=161):
    """Round-trip-friendly synthetic section: exact CST coefficients, so the
    fit should recover them near-exactly (Selig-ordering data path)."""
    rng = np.random.default_rng(0)
    A_upper = 0.15 + 0.02 * rng.standard_normal(n + 1)
    A_lower = -(0.10 + 0.02 * rng.standard_normal(n + 1))
    psi = cosine_spacing(npoint)
    X = coords_from_A(A_upper, A_lower, 0.0, 0.0, psi, N1=0.5, N2=1.0)
    return A_upper, A_lower, X


def test_fit_cst_returns_fit_result():
    _, _, X = _synthetic_airfoil()
    result = fit_cst(X[0], X[1], n=8, N1=0.5, N2=1.0)
    assert isinstance(result, FitResult)
    assert result.A_upper.shape == (9,)
    assert result.A_lower.shape == (9,)
    assert result.rms >= 0.0
    assert result.gram_condition >= 1.0


def test_fit_cst_lower_coefficients_are_negative():
    _, _, X = _synthetic_airfoil()
    result = fit_cst(X[0], X[1], n=8, N1=0.5, N2=1.0)
    # BINDING convention (src/cins/CLAUDE.md): A_l,i < 0 for a conventional
    # airfoil (this synthetic section is built that way on purpose).
    assert np.all(result.A_lower < 0.0)


def test_fit_cst_recovers_exact_coefficients_from_own_construction():
    A_upper, A_lower, X = _synthetic_airfoil(n=8, npoint=241)
    result = fit_cst(X[0], X[1], n=8, N1=0.5, N2=1.0)
    np.testing.assert_allclose(result.A_upper, A_upper, atol=1e-6)
    np.testing.assert_allclose(result.A_lower, A_lower, atol=1e-6)
    assert result.rms < 1e-9


def test_fit_cst_handles_mfoil_ccw_ordering():
    m = make_mfoil(naca="2412", npanel=199)
    X = m.geom.xpoint  # TE-lower -> LE -> TE-upper (mfoil CCW)
    result = fit_cst(X[0], X[1], n=8, N1=0.5, N2=1.0)
    assert result.rms < 1e-3


def test_fit_cst_handles_selig_ordering():
    """Selig .dat convention: TE -> upper -> LE -> lower -> TE (reverse of
    mfoil's CCW order). fit_cst must not care about direction."""
    m = make_mfoil(naca="2412", npanel=199)
    X_ccw = m.geom.xpoint
    X_selig = X_ccw[:, ::-1]  # flip direction: TE-upper -> LE -> TE-lower
    result = fit_cst(X_selig[0], X_selig[1], n=8, N1=0.5, N2=1.0)
    assert result.rms < 1e-3
    # direction-agnostic: must match the CCW-ordering fit exactly
    result_ccw = fit_cst(X_ccw[0], X_ccw[1], n=8, N1=0.5, N2=1.0)
    np.testing.assert_allclose(result.A_lower, result_ccw.A_lower, atol=1e-10)
    np.testing.assert_allclose(result.A_upper, result_ccw.A_upper, atol=1e-10)


def test_fit_cst_te_gap_override():
    _, _, X = _synthetic_airfoil()
    gap = 0.004
    result = fit_cst(X[0], X[1], n=8, N1=0.5, N2=1.0, te_gap=gap)
    assert result.zeta_T_upper == gap / 2
    assert result.zeta_T_lower == -gap / 2


def test_fit_cst_round_trip_matches_rms():
    """surface() evaluated from the fitted coefficients must reproduce the
    fit within the reported RMS (dossier gate requirement)."""
    m = make_mfoil(naca="0012", npanel=199)
    X = m.geom.xpoint
    n = 8
    result = fit_cst(X[0], X[1], n=n, N1=0.5, N2=1.0)

    from cins.cst.basis import surface

    chord = X[0, :].max() - X[0, :].min()
    x0 = X[0, :].min()
    le_idx = int(np.argmin(X[0, :]))
    psi_lower = (X[0, : le_idx + 1][::-1] - x0) / chord
    zeta_lower = X[1, : le_idx + 1][::-1] / chord
    psi_upper = (X[0, le_idx:] - x0) / chord
    zeta_upper = X[1, le_idx:] / chord

    z_upper_fit = surface(psi_upper, result.A_upper, result.zeta_T_upper, 0.5, 1.0)
    z_lower_fit = surface(psi_lower, result.A_lower, result.zeta_T_lower, 0.5, 1.0)
    resid = np.concatenate([z_upper_fit - zeta_upper, z_lower_fit - zeta_lower])
    rms = float(np.sqrt(np.mean(resid**2)))
    assert rms <= result.rms * 5 + 1e-12  # same order of magnitude
