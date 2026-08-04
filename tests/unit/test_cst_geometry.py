"""Unit tests for cins.cst.geometry (dossier §7.3).

Node ordering (src/cins/CLAUDE.md, BINDING): TE lower -> LE -> TE upper,
counterclockwise, LE point not duplicated.
"""

from __future__ import annotations

import numpy as np

from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.solver.mfoil_adapter import make_mfoil
from tests._mfoil_coords import mfoil_from_coords

# --------------------------------------------------------------------------
# cosine_spacing
# --------------------------------------------------------------------------


def test_cosine_spacing_endpoints():
    psi = cosine_spacing(50)
    assert psi[0] == 0.0
    assert psi[-1] == 1.0


def test_cosine_spacing_monotonic():
    psi = cosine_spacing(80)
    assert np.all(np.diff(psi) > 0)


def test_cosine_spacing_clusters_at_ends():
    # spacing near the ends must be smaller than spacing near mid-chord
    psi = cosine_spacing(41)
    d = np.diff(psi)
    mid = len(d) // 2
    assert d[0] < d[mid]
    assert d[-1] < d[mid]


def test_cosine_spacing_length():
    psi = cosine_spacing(37)
    assert psi.shape == (37,)


# --------------------------------------------------------------------------
# coords_from_A
# --------------------------------------------------------------------------


def _simple_A(n=6):
    # a mild, physically plausible cambered section
    A_upper = np.linspace(0.18, 0.05, n + 1)
    A_lower = -np.linspace(0.12, 0.03, n + 1)
    return A_upper, A_lower


def test_coords_from_A_shape():
    psi = cosine_spacing(21)
    A_u, A_l = _simple_A()
    X = coords_from_A(A_u, A_l, 0.0, 0.0, psi)
    assert X.shape == (2, 2 * len(psi) - 1)


def test_coords_from_A_le_not_duplicated():
    psi = cosine_spacing(21)
    A_u, A_l = _simple_A()
    X = coords_from_A(A_u, A_l, 0.0, 0.0, psi)
    assert np.sum(X[0, :] == 0.0) == 1


def test_coords_from_A_ordering_te_lower_to_le_to_te_upper():
    psi = cosine_spacing(21)
    A_u, A_l = _simple_A()
    X = coords_from_A(A_u, A_l, 0.0, 0.0, psi)
    n = X.shape[1]
    # first point: TE (x=1), on the lower branch (z <= upper TE z)
    assert X[0, 0] == 1.0
    # last point: TE (x=1), on the upper branch
    assert X[0, -1] == 1.0
    # LE (x=0) sits at the midpoint index
    le_idx = np.argmin(X[0, :])
    assert le_idx == n // 2


def test_coords_from_A_ccw_orientation():
    """mfoil's own CCW test (vendor/mfoil/mfoil.py set_coords, wrap-around
    sum of (dx)*(z_i+z_{i-1})) must be positive — this is exactly the
    condition build_wake relies on (src/cins/CLAUDE.md)."""
    psi = cosine_spacing(41)
    A_u, A_l = _simple_A()
    X = coords_from_A(A_u, A_l, 0.0, 0.0, psi)
    signed = 0.0
    for i in range(X.shape[1]):
        signed += (X[0, i] - X[0, i - 1]) * (X[1, i] + X[1, i - 1])
    assert signed > 0.0


def test_coords_from_A_te_gap_applied():
    psi = cosine_spacing(15)
    A_u, A_l = _simple_A()
    gap = 0.002
    X = coords_from_A(A_u, A_l, gap / 2, -gap / 2, psi)
    # TE point at start (lower) and end (upper) reflect the half-gaps
    assert X[1, 0] == pytest_approx(-gap / 2)
    assert X[1, -1] == pytest_approx(gap / 2)


def pytest_approx(v, abs=1e-12):
    import pytest as _pytest

    return _pytest.approx(v, abs=abs)


# --------------------------------------------------------------------------
# mfoil acceptance (integration-flavoured, still "unit": fast, deterministic)
# --------------------------------------------------------------------------


def test_coords_from_A_accepted_by_mfoil_panels():
    psi = cosine_spacing(199)
    A_u, A_l = _simple_A()
    X = coords_from_A(A_u, A_l, 0.0, 0.0, psi)
    m = mfoil_from_coords(X, npanel=159)
    assert m.foil.N == 160
    assert np.all(np.isfinite(m.foil.x))


def test_coords_from_A_cambered_section_gives_sensible_inviscid_cl():
    """A cambered section at alpha=0 should produce a positive, physically
    reasonable lift coefficient inviscid (sanity, not a pinned gate)."""
    psi = cosine_spacing(199)
    A_u, A_l = _simple_A()
    X = coords_from_A(A_u, A_l, 0.0, 0.0, psi)
    m = mfoil_from_coords(X, npanel=159)
    m.setoper(alpha=0.0, Re=1e6)
    m.param.doplot = False
    m.param.verb = 0
    from cins.solver.mfoil_adapter import mfoil_module

    mfoil_module().solve_inviscid(m)
    assert 0.0 < m.post.cl < 1.5


def test_naca_geom_matches_expected_ordering():
    """Cross-check against mfoil's own naca_points ordering (ground truth
    for the CLAUDE.md convention): TE lower -> LE -> TE upper, LE once."""
    m = make_mfoil(naca="2412", npanel=199)
    X = m.geom.xpoint
    assert X[0, 0] == pytest_approx(1.0, abs=1e-9)
    assert X[0, -1] == pytest_approx(1.0, abs=1e-9)
    le_idx = int(np.argmin(X[0, :]))
    assert pytest_approx(0.0, abs=1e-9) == X[0, le_idx]
    assert np.sum(X[0, :] == X[0, le_idx]) == 1
