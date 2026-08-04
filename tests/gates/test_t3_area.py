"""Gate T3 (dossier §7.4): area_row must match adaptive numerical quadrature of a
fitted real airfoil to 1e-10. 'A cheap, decisive check that the Beta-function
algebra is right.'"""

import numpy as np
from scipy.integrate import quad

from cins.config import load_config
from cins.cst.basis import class_fn, surface
from cins.cst.constraints import area_row
from cins.cst.fit import fit_cst
from cins.solver.mfoil_adapter import make_mfoil

CFG = load_config()
TOL = CFG.gates.t3_area_quadrature_tol


def _fitted_2412(n=8):
    m = make_mfoil(naca="2412", npanel=199)
    X = m.geom.xpoint
    return fit_cst(X[0], X[1], n)


def test_area_row_matches_quadrature_on_fitted_naca2412():
    fit = _fitted_2412(n=8)
    n = len(fit.A_upper) - 1
    A = np.concatenate([fit.A_upper, fit.A_lower])
    g, te_coeff = area_row(n, n)

    # analytic area from the row: g.A + te_coeff terms
    area_analytic = g @ A + te_coeff @ np.array([fit.zeta_T_upper, fit.zeta_T_lower])

    # independent adaptive quadrature of (zeta_u - zeta_l)
    def thickness(psi):
        zu = surface(np.array([psi]), fit.A_upper, fit.zeta_T_upper)[0]
        zl = surface(np.array([psi]), fit.A_lower, fit.zeta_T_lower)[0]
        return zu - zl

    area_quad, err = quad(thickness, 0.0, 1.0, epsabs=1e-13, epsrel=1e-13, limit=200)
    assert err < TOL
    assert abs(area_analytic - area_quad) < TOL


def test_area_row_single_bernstein_terms_exact():
    """Each basis-function integral against the class function equals
    K_i * B(i + N1 + 1, n - i + N2 + 1) — checked term by term by quadrature."""
    from math import comb

    from scipy.special import beta as beta_fn

    n = 6
    for i in range(n + 1):
        K = comb(n, i)
        analytic = K * beta_fn(i + 1.5, n - i + 2.0)  # N1=0.5, N2=1.0

        val, err = quad(
            lambda p, i=i, K=K: class_fn(np.array([p]))[0] * K * p**i * (1 - p) ** (n - i),
            0.0, 1.0, epsabs=1e-14, epsrel=1e-14, limit=200,
        )
        assert abs(analytic - val) < 1e-12
