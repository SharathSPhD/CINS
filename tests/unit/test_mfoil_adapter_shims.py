"""Adapter shims for two vendored-mfoil constructor bugs (ADR-0002).

vendor/mfoil/mfoil.py has three tuple/list/array-called-as-function bugs:
  - set_coords: ``X.shape(1)`` (x2) -> TypeError for ANY coords input;
  - naca_points 5-digit branch: ``mv(n)``, ``cv(n)``, ``x(i)`` -> TypeError
    for ANY 5-digit code.
The adapter must replace both module-level functions with corrected copies so
``make_mfoil(coords=...)`` and ``make_mfoil(naca='23012')`` work with the
vendor file untouched.
"""

from __future__ import annotations

import numpy as np

from cins.solver.mfoil_adapter import make_mfoil


def _naca0012_coords() -> np.ndarray:
    """(2, N) CCW coordinates from the (working) vendored 4-digit generator."""
    m = make_mfoil(naca="0012", npanel=99)
    return np.array(m.geom.xpoint, copy=True)


class TestSetCoordsShim:
    def test_make_mfoil_from_coords_constructs(self):
        X = _naca0012_coords()
        m = make_mfoil(coords=X, npanel=99)
        assert m.geom.npoint == X.shape[1]
        assert np.isclose(m.geom.chord, X[0, :].max() - X[0, :].min())
        # make_panels ran on the coords: panel nodes exist and are CCW
        assert m.foil.x.shape[0] == 2
        assert m.foil.x.shape[1] == 100  # npanel+1 nodes

    def test_transposed_input_accepted(self):
        # set_coords documents rows-or-columns input; (N, 2) must also work
        X = _naca0012_coords()
        m = make_mfoil(coords=X.T, npanel=99)
        assert m.geom.npoint == X.shape[1]

    def test_cw_input_flipped_to_ccw(self):
        # vendor contract: CW or CCW accepted, stored orientation identical
        X = _naca0012_coords()
        m_ccw = make_mfoil(coords=X, npanel=99)
        m_cw = make_mfoil(coords=np.fliplr(X), npanel=99)
        assert np.allclose(m_ccw.geom.xpoint, m_cw.geom.xpoint)


class TestNaca5Shim:
    def test_make_mfoil_naca_23012(self):
        m = make_mfoil(naca="23012", npanel=99)
        assert m.geom.name == "NACA 23012"
        assert m.geom.npoint == 201  # 2*100+1, same as 4-digit path
        x, z = m.geom.xpoint
        # ~12% thick: max thickness of the raw point set
        n_side = 101
        zl = z[:n_side][::-1]  # TE lower -> LE, reversed to LE -> TE
        zu = np.concatenate(([z[n_side - 1]], z[n_side:]))
        thick = (zu - zl).max()
        assert 0.11 < thick < 0.13
        # cambered: mean line positive over the front of the section
        camber = (zu + zl) / 2.0
        assert camber.max() > 0.015  # 23012 max camber ~2% chord

    def test_naca5_camber_piecewise_formula(self):
        # spot-check the corrected coefficients: for 230XX, m=.2025, cc=15.957
        m = make_mfoil(naca="23006", npanel=99)
        x, z = m.geom.xpoint
        n_side = 101
        zl = z[:n_side][::-1]
        zu = np.concatenate(([z[n_side - 1]], z[n_side:]))
        xs = x[n_side - 1 :]
        camber = (zu + zl) / 2.0
        mm, cc = 0.2025, 15.957
        expected = np.where(
            xs <= mm,
            (cc / 6.0) * (xs**3 - 3 * mm * xs**2 + mm**2 * (3 - mm) * xs),
            (cc / 6.0) * mm**3 * (1 - xs),
        )
        assert np.allclose(camber, expected, atol=1e-3)

    def test_invalid_5digit_still_rejected(self):
        # the vendor's validity assert must survive the shim
        import pytest

        with pytest.raises(AssertionError):
            make_mfoil(naca="23112", npanel=99)  # digit 3 != 0
