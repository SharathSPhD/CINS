"""Unit tests for recover_omega (T5 review finding: the ω edge cases were
unexercised by T7's archived evidence). Covers the α channel, the θ-row
fallback, and the ω=0 full-rejection edge."""

import numpy as np

from cins.solver.newton import recover_omega


def test_alpha_channel_recovers_exact_omega():
    for om in (1.0, 0.42, 6e-4):
        a0, da = 2.0, 0.8
        assert np.isclose(recover_omega(a0, a0 + om * da, da, None, None, None), om)


def test_theta_fallback_recovers_omega_when_alpha_fixed():
    rng = np.random.default_rng(7)
    th0 = 0.01 + 0.005 * rng.random(50)
    dth = 1e-4 * rng.standard_normal(50)
    for om in (1.0, 0.37, 4.2e-4):
        th1 = th0 + om * dth
        assert np.isclose(recover_omega(2.0, 2.0, 0.0, th0, th1, dth), om, rtol=1e-12)


def test_full_rejection_freezes_a_step():
    """omega=0 (update_state rejected everything) must propagate as 0, not 1."""
    th0 = np.array([0.01, 0.02, 0.03])
    dth = np.array([1e-3, -2e-3, 5e-4])
    assert recover_omega(2.0, 2.0, 0.0, th0, th0.copy(), dth) == 0.0


def test_degenerate_zero_dth_defaults_to_one():
    th0 = np.array([0.01, 0.02])
    assert recover_omega(2.0, 2.0, 0.0, th0, th0, np.zeros(2)) == 1.0


def test_clipping_to_unit_interval():
    assert recover_omega(2.0, 2.0 + 1.5 * 0.8, 0.8, None, None, None) == 1.0
    assert recover_omega(2.0, 2.0 - 0.1 * 0.8, 0.8, None, None, None) == 0.0
