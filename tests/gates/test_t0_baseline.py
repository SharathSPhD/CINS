"""Gate T0: environment + mfoil baseline (dossier §7.1).

'Verify the baseline before touching anything.' NACA 2412, alpha=2, Re=1e6 must
converge viscous with sane coefficients. Numbers pinned from the 2026-08-04 run
(regression tolerance: mfoil is deterministic, so exact-ish).
"""

import numpy as np
import pytest

from cins.config import load_config
from cins.solver.mfoil_adapter import make_mfoil

CFG = load_config()


@pytest.fixture(scope="module")
def solved():
    m = make_mfoil(naca="2412", npanel=CFG.paneling.npanel)
    m.setoper(
        alpha=CFG.operating.alpha_deg,
        Re=CFG.operating.Re,
    )
    m.solve()
    return m


def test_baseline_converges(solved):
    assert solved.glob.conv


def test_baseline_cl_in_gate_range(solved):
    lo, hi = CFG.gates.t0_cl_range
    assert lo < solved.post.cl < hi


def test_baseline_pinned_coefficients(solved):
    # pinned 2026-08-04, mfoil v2023-06-28, npanel=199, alpha=2, Re=1e6
    assert solved.post.cl == pytest.approx(0.449351, abs=1e-4)
    assert solved.post.cd == pytest.approx(0.005778, abs=5e-5)
    assert solved.post.cm == pytest.approx(-0.048030, abs=1e-4)


def test_global_system_shapes(solved):
    """The shapes the extended Newton system (T5) will append to."""
    nsys = solved.glob.Nsys
    assert solved.glob.U.shape == (4, nsys)
    assert solved.glob.R.shape == (3 * nsys,)
    assert solved.glob.R_U.shape == (3 * nsys, 4 * nsys)
    assert solved.glob.R_x.shape == (3 * nsys, nsys)


def test_cp_distribution_available(solved):
    cp = np.asarray(solved.post.cp)
    assert cp.shape[0] >= solved.foil.N
    assert np.all(np.isfinite(cp))
