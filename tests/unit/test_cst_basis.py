"""Unit tests for cins.cst.basis (dossier §3.1-3.3, §3.5-3.6).

Red-first: written before src/cins/cst/basis.py exists.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cins.cst.basis import (
    bernstein,
    bernstein_matrix,
    class_fn,
    dsurface_dA,
    le_modification,
    surface,
)

# --------------------------------------------------------------------------
# bernstein / bernstein_matrix
# --------------------------------------------------------------------------


def test_bernstein_partition_of_unity():
    """Sum_i S_i(psi) = 1 for all psi (Bernstein polynomials of a fixed degree
    always sum to (psi + (1-psi))^n = 1)."""
    psi = np.linspace(0.0, 1.0, 51)
    n = 8
    total = sum(bernstein(n, i, psi) for i in range(n + 1))
    np.testing.assert_allclose(total, np.ones_like(psi), atol=1e-12)


def test_bernstein_matrix_shape():
    psi = np.linspace(0.0, 1.0, 11)
    n = 5
    M = bernstein_matrix(n, psi)
    assert M.shape == (11, 6)


def test_bernstein_matrix_matches_bernstein():
    psi = np.array([0.0, 0.1, 0.37, 0.9, 1.0])
    n = 6
    M = bernstein_matrix(n, psi)
    for i in range(n + 1):
        np.testing.assert_allclose(M[:, i], bernstein(n, i, psi))


def test_bernstein_endpoints():
    # S_0(0) = 1, S_i(0) = 0 for i>0 ; S_n(1) = 1, S_i(1) = 0 for i<n
    n = 7
    row0 = bernstein_matrix(n, np.array([0.0]))[0]
    row1 = bernstein_matrix(n, np.array([1.0]))[0]
    expected0 = np.zeros(n + 1)
    expected0[0] = 1.0
    expected1 = np.zeros(n + 1)
    expected1[-1] = 1.0
    np.testing.assert_allclose(row0, expected0, atol=1e-12)
    np.testing.assert_allclose(row1, expected1, atol=1e-12)


# --------------------------------------------------------------------------
# class_fn
# --------------------------------------------------------------------------


def test_class_fn_vanishes_at_endpoints():
    psi = np.array([0.0, 1.0])
    C = class_fn(psi, N1=0.5, N2=1.0)
    np.testing.assert_allclose(C, [0.0, 0.0], atol=1e-12)


def test_class_fn_value_at_midpoint():
    C = class_fn(np.array([0.25]), N1=0.5, N2=1.0)
    np.testing.assert_allclose(C, [0.25**0.5 * 0.75], atol=1e-12)


def test_class_fn_default_args_match_dossier():
    # dossier §3.1: round-nose sharp-tail default N1=0.5, N2=1.0
    psi = np.array([0.3])
    np.testing.assert_allclose(class_fn(psi), class_fn(psi, N1=0.5, N2=1.0))


# --------------------------------------------------------------------------
# surface
# --------------------------------------------------------------------------


def test_surface_matches_manual_formula():
    psi = np.linspace(0.0, 1.0, 21)
    n = 4
    A = np.array([0.2, 0.15, 0.1, 0.05, 0.02])
    zeta_T = 0.001
    zeta = surface(psi, A, zeta_T, N1=0.5, N2=1.0)
    S = bernstein_matrix(n, psi)
    C = class_fn(psi, 0.5, 1.0)
    expected = C * (S @ A) + psi * zeta_T
    np.testing.assert_allclose(zeta, expected, atol=1e-12)


def test_surface_le_identity_zero_regardless_of_A():
    # C(0) = 0 for N1>0, and psi*zeta_T = 0 at psi=0 => zeta(0) = 0 always.
    A = np.array([0.5, -0.3, 0.9])
    zeta = surface(np.array([0.0]), A, zeta_T=0.123, N1=0.5, N2=1.0)
    np.testing.assert_allclose(zeta, [0.0], atol=1e-12)


def test_surface_te_identity_equals_zeta_T():
    # C(1) = 0 for N2>0, so zeta(1) = zeta_T exactly.
    A = np.array([0.5, -0.3, 0.9])
    zeta = surface(np.array([1.0]), A, zeta_T=0.0042, N1=0.5, N2=1.0)
    np.testing.assert_allclose(zeta, [0.0042], atol=1e-12)


def test_surface_complex_step_safe_with_complex_A():
    """Complex-step differentiation drives A complex; surface() must not
    abs/max/min/compare psi or A anywhere on the path."""
    psi = np.linspace(0.0, 1.0, 15)
    n = 4
    A = np.array([0.2, 0.15, 0.1, 0.05, 0.02], dtype=complex)
    h = 1e-30
    A_pert = A.copy()
    A_pert[2] += 1j * h
    zeta = surface(psi, A_pert, zeta_T=0.0, N1=0.5, N2=1.0)
    assert np.iscomplexobj(zeta)
    dzeta_dA2_cs = zeta.imag / h
    # cross-check against dsurface_dA column 2 (real-valued, design-independent)
    M = dsurface_dA(psi, n, N1=0.5, N2=1.0)
    np.testing.assert_allclose(dzeta_dA2_cs, M[:, 2], atol=1e-8)


# --------------------------------------------------------------------------
# dsurface_dA
# --------------------------------------------------------------------------


def test_dsurface_dA_shape():
    psi = np.linspace(0.0, 1.0, 9)
    n = 6
    M = dsurface_dA(psi, n, N1=0.5, N2=1.0)
    assert M.shape == (9, 7)


def test_dsurface_dA_matches_surface_columns():
    """dsurface_dA[:, i] must equal surface() evaluated with a one-hot A_i,
    zeta_T=0 (since surface is linear in A with that convention)."""
    psi = np.linspace(0.0, 1.0, 13)
    n = 5
    M = dsurface_dA(psi, n, N1=0.5, N2=1.0)
    for i in range(n + 1):
        A = np.zeros(n + 1)
        A[i] = 1.0
        col = surface(psi, A, zeta_T=0.0, N1=0.5, N2=1.0)
        np.testing.assert_allclose(M[:, i], col, atol=1e-12)


def test_dsurface_dA_matches_finite_difference():
    psi = np.linspace(0.01, 0.99, 11)
    n = 4
    A0 = np.array([0.18, 0.12, 0.08, 0.05, 0.02])
    M = dsurface_dA(psi, n, N1=0.5, N2=1.0)
    eps = 1e-6
    for i in range(n + 1):
        Ap = A0.copy()
        Ap[i] += eps
        Am = A0.copy()
        Am[i] -= eps
        fd = (
            surface(psi, Ap, 0.0, 0.5, 1.0) - surface(psi, Am, 0.0, 0.5, 1.0)
        ) / (2 * eps)
        np.testing.assert_allclose(M[:, i], fd, atol=1e-6)


def test_dsurface_dA_is_cached_and_returns_independent_copies():
    psi = np.linspace(0.0, 1.0, 5)
    n = 3
    M1 = dsurface_dA(psi, n)
    M2 = dsurface_dA(psi.copy(), n)
    np.testing.assert_allclose(M1, M2)
    M1[0, 0] = 999.0
    M3 = dsurface_dA(psi, n)
    # mutating a returned matrix must not corrupt the cache
    assert M3[0, 0] != 999.0


def test_dsurface_dA_cache_hits_on_value_equal_psi_objects():
    """Cache-key semantics (basis.py docstring): psi arrays that are equal by
    VALUE but distinct objects must hit the same cache entry — the returned
    matrices are bit-identical, and the underlying cached buffer is reused
    (verified via the module's cache_info hit counter)."""
    from cins.cst.basis import _dsurface_dA_cached

    _dsurface_dA_cached.cache_clear()
    psi_a = np.linspace(0.0, 1.0, 7)
    psi_b = np.linspace(0.0, 1.0, 7).copy()  # same values, different object
    assert psi_a is not psi_b
    M_a = dsurface_dA(psi_a, 3, N1=0.5, N2=1.0)
    M_b = dsurface_dA(psi_b, 3, N1=0.5, N2=1.0)
    info = _dsurface_dA_cached.cache_info()
    assert info.misses == 1 and info.hits == 1  # second call reused the entry
    assert M_a.tobytes() == M_b.tobytes()  # bit-identical


# --------------------------------------------------------------------------
# le_modification
# --------------------------------------------------------------------------


def test_le_modification_vanishes_at_le_and_te():
    z = le_modification(np.array([0.0, 1.0]), a_lem=0.05)
    np.testing.assert_allclose(z, [0.0, 0.0], atol=1e-12)


def test_le_modification_zero_when_amplitude_zero():
    psi = np.linspace(0.0, 1.0, 10)
    z = le_modification(psi, a_lem=0.0)
    np.testing.assert_allclose(z, np.zeros_like(psi), atol=1e-12)


def test_le_modification_has_finite_slope_at_le():
    """The whole point of the LEM term (dossier §3.5 fix #1): finite dζ/dψ
    at the nose, unlike the sqrt(psi) singularity of the base CST term."""
    a_lem = 0.05
    h = 1e-6
    z_h = le_modification(np.array([h]), a_lem)[0]
    z_0 = le_modification(np.array([0.0]), a_lem)[0]
    slope = (z_h - z_0) / h
    assert np.isfinite(slope)
    np.testing.assert_allclose(slope, a_lem, rtol=1e-3)


# --------------------------------------------------------------------------
# Property-based tests (hypothesis) — dossier tests/CLAUDE.md encouragement
# --------------------------------------------------------------------------

_n = 5
_psi_grid = np.linspace(0.0, 1.0, 17)
_coef = st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False)
_A_strategy = st.lists(_coef, min_size=_n + 1, max_size=_n + 1).map(np.array)


@given(A1=_A_strategy, A2=_A_strategy)
@settings(max_examples=50)
def test_property_surface_linear_in_A(A1, A2):
    z1 = surface(_psi_grid, A1, zeta_T=0.0, N1=0.5, N2=1.0)
    z2 = surface(_psi_grid, A2, zeta_T=0.0, N1=0.5, N2=1.0)
    z_sum = surface(_psi_grid, A1 + A2, zeta_T=0.0, N1=0.5, N2=1.0)
    np.testing.assert_allclose(z_sum, z1 + z2, atol=1e-9)


@given(A=_A_strategy)
@settings(max_examples=25)
def test_property_endpoint_identities(A):
    # S(0) = A_0, S(1) = A_n (bernstein endpoint identities, dossier §3.2)
    S = bernstein_matrix(_n, np.array([0.0, 1.0]))
    s0 = S[0] @ A
    s1 = S[1] @ A
    assert s0 == pytest.approx(A[0], abs=1e-10)
    assert s1 == pytest.approx(A[-1], abs=1e-10)


@given(A=_A_strategy, i=st.integers(min_value=0, max_value=_n))
@settings(max_examples=25)
def test_property_dsurface_dA_column_matches_fd(A, i):
    eps = 1e-6
    Ap = A.copy()
    Ap[i] += eps
    Am = A.copy()
    Am[i] -= eps
    fd = (
        surface(_psi_grid, Ap, 0.0, 0.5, 1.0) - surface(_psi_grid, Am, 0.0, 0.5, 1.0)
    ) / (2 * eps)
    M = dsurface_dA(_psi_grid, _n, N1=0.5, N2=1.0)
    np.testing.assert_allclose(M[:, i], fd, atol=1e-5)
