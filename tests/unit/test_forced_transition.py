"""ADR-0003: forced-transition (trip) shim.

Verifies the two-part mechanism -- ``M.vsol.turb`` frozen to a node-index
trip pattern AND the natural-transition station equation
(``residual_transition``) replaced with an XFOIL-trip-style onset closure
(``_residual_transition_forced``) -- actually converges, is dynamically
consistent (no hidden inconsistent residual row), and cleanly reverts to
natural transition.

Baseline (natural-transition) numbers are pinned in
``tests/gates/test_t0_baseline.py`` (NACA 2412, alpha=2, Re=1e6, npanel=199):
cl=0.449351, cd=0.005778. Reused here (same tolerance) as the
release_transition regression check.
"""

from __future__ import annotations

import numpy as np
import pytest

from cins.config import load_config
from cins.solver.mfoil_adapter import (
    forced_transition,
    make_mfoil,
    mfoil_module,
    release_transition,
    set_forced_transition,
)

CFG = load_config()
_MM = mfoil_module()


def _natural_solve():
    m = make_mfoil(naca="2412", npanel=CFG.paneling.npanel)
    m.setoper(alpha=CFG.operating.alpha_deg, Re=CFG.operating.Re)
    m.solve()
    return m


def _forced_solve(xtr: float, *, release: bool = True):
    """Natural warm solve (to populate vsol.Is / an initial BL state), then
    re-solve the coupled Newton system with transition forced at x/c=xtr on
    both surfaces.

    The shim is process-global (ADR-0003): if ``release`` is True (default),
    ``release_transition()`` runs before returning so nothing leaks into
    other tests/fixtures. Post-processed quantities (``m.post.*``,
    ``m.glob.conv``) are already computed by ``calc_force`` and remain valid
    after release. Pass ``release=False`` only when the test itself needs to
    poke the still-forced state (e.g. rebuilding the residual) and takes
    responsibility for calling ``release_transition()`` itself.
    """
    m = _natural_solve()
    set_forced_transition(m, xtr, xtr)
    m.glob.conv = False
    _MM.solve_coupled(m)
    _MM.calc_force(m)
    if release:
        release_transition()
    return m


@pytest.fixture(scope="module")
def natural():
    return _natural_solve()


@pytest.fixture(scope="module")
def forced_5pct():
    return _forced_solve(0.05)


@pytest.fixture(scope="module")
def forced_30pct():
    return _forced_solve(0.30)


class TestForcedTripConverges:
    """Acceptance case 1: trip at 5%/5% must actually converge, not stall."""

    def test_converged(self, forced_5pct):
        assert forced_5pct.glob.conv

    def test_rnorm_below_newton_rtol(self, forced_5pct):
        # glob.conv is only set True when Rnorm < param.rtol inside
        # solve_coupled; re-derive it independently as a second check.
        assert np.linalg.norm(forced_5pct.glob.R) < forced_5pct.param.rtol

    def test_cd_strictly_greater_than_natural(self, natural, forced_5pct):
        # forcing an early trip adds turbulent wetted area -> more drag
        assert forced_5pct.post.cd > natural.post.cd

    def test_cl_within_10pct_of_natural(self, natural, forced_5pct):
        assert abs(forced_5pct.post.cl - natural.post.cl) < 0.10 * abs(natural.post.cl)


class TestTripLocationMonotonicity:
    """Acceptance case 2: trip at 30%/30% converges; drag sits strictly
    between the aggressive 5% trip and the (aft-most-possible) natural
    transition location."""

    def test_converged(self, forced_30pct):
        assert forced_30pct.glob.conv

    def test_cd_between_5pct_trip_and_natural(self, natural, forced_5pct, forced_30pct):
        assert natural.post.cd < forced_30pct.post.cd < forced_5pct.post.cd


class TestReleaseRestoresNaturalTransition:
    """Acceptance case 3: release_transition() must restore BOTH shimmed
    functions -- a re-solve after release should reproduce the pinned
    natural-transition baseline (test_t0_baseline.py), not some artifact of
    the forced solve's state."""

    def test_release_then_resolve_matches_natural_baseline(self):
        m = _natural_solve()
        set_forced_transition(m, 0.05, 0.05)
        m.glob.conv = False
        _MM.solve_coupled(m)

        release_transition()
        m.glob.conv = False
        _MM.solve_coupled(m)
        _MM.calc_force(m)

        assert m.glob.conv
        assert m.post.cl == pytest.approx(0.449351, abs=1e-3)
        assert m.post.cd == pytest.approx(0.005778, abs=2e-4)

    def test_update_transition_and_residual_transition_both_restored(self):
        before_ut = _MM.update_transition
        before_rt = _MM.residual_transition
        m = _natural_solve()
        set_forced_transition(m, 0.05, 0.05)
        assert _MM.update_transition is not before_ut
        assert _MM.residual_transition is not before_rt
        release_transition()
        assert _MM.update_transition is before_ut
        assert _MM.residual_transition is before_rt


class TestResidualConsistency:
    """Acceptance case 4: after a converged forced solve, rebuilding the
    global system must reproduce (not merely have once produced) a tiny
    residual -- i.e. no station's row was satisfied only transiently, and
    there is no hidden inconsistent row that Newton happened to step past."""

    def test_rebuilt_residual_norm_tiny(self):
        m = _forced_solve(0.05, release=False)
        try:
            _MM.build_glob_sys(m)
            assert np.linalg.norm(m.glob.R) < 1e-8
        finally:
            release_transition()


class TestContextManager:
    def test_forced_transition_context_manager_round_trips(self):
        before_ut = _MM.update_transition
        before_rt = _MM.residual_transition
        m = _natural_solve()
        with forced_transition(m, 0.05, 0.05):
            assert _MM.update_transition is not before_ut
            assert _MM.residual_transition is not before_rt
            m.glob.conv = False
            _MM.solve_coupled(m)
            assert m.glob.conv
        assert _MM.update_transition is before_ut
        assert _MM.residual_transition is before_rt


class TestForcedTurbPattern:
    """set_forced_transition itself: node-index pattern by x/c threshold,
    wake always turbulent, refusal to laminarize."""

    def test_turb_pattern_matches_xtr_threshold(self):
        m = _natural_solve()
        set_forced_transition(m, 0.05, 0.05)
        chord = m.geom.chord
        x = m.foil.x[0]
        for si in (0, 1):
            Is = np.fromiter(m.vsol.Is[si], dtype=int)
            turb = np.asarray(m.vsol.turb[Is])
            want = (x[Is] / chord >= 0.05).astype(int)
            assert np.array_equal(turb, want)
        release_transition()

    def test_wake_always_turbulent(self):
        m = _natural_solve()
        set_forced_transition(m, 0.05, 0.05)
        Iw = np.fromiter(m.vsol.Is[2], dtype=int)
        assert np.all(m.vsol.turb[Iw] == 1)
        release_transition()

    def test_laminarizing_aft_transition_rejected(self):
        m = _natural_solve()
        # natural transition is well aft of the LE; forcing trip forward of
        # it is fine, but forcing it AFT of already-turbulent nodes would
        # require laminarizing -- not supported (ADR-0003).
        with pytest.raises(ValueError):
            set_forced_transition(m, 0.99, 0.99)
