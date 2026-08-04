"""T6: diagnostics D-1..D-6 (dossier §7.7, SPEC.md §6).

Unit-level checks on the instrumentation contract T5's Newton solver will code
against: NewtonDiagnostics recording/round-trip, the D-6 convergence-order
estimator (STATS_PROTOCOL.md H3), D-2 rank detection, and the D-4 row-norm
profile shape. Figure builders are smoke-tested for structure only — no test
depends on matplotlib rendering (tests/CLAUDE.md).
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.figure import Figure

from cins.config import load_config
from cins.diagnostics.plots import (
    fig_d1_residuals,
    fig_d4_row_norm_profile,
    fig_d5_transition_history,
    fig_d6_convergence,
)
from cins.diagnostics.recorder import DiagnosticsReport, NewtonDiagnostics

CFG = load_config()


# --------------------------------------------------------------------------- #
# Recorder round-trip
# --------------------------------------------------------------------------- #


def test_record_finalize_json_round_trip(tmp_path):
    diag = NewtonDiagnostics(config=CFG)
    diag.record_static(
        gram_condition=1.23e5,
        dof_accounting={"n_A": 18, "M": 10, "K": 9, "squareness_residual": 0},
    )
    for it in range(4):
        diag.record_iteration(
            it,
            R_norm=10.0 ** (-it),
            T_norm=5.0 ** (-it),
            G_norm=1e-12,
            transition_xt=(0.05, 0.06),
            omega=1.0,
            dA_norm=0.01,
            extra={"note": f"iter{it}"},
        )

    report = diag.finalize(tmp_path, run_manifest={"airfoil": "2412"})
    assert isinstance(report, DiagnosticsReport)

    out_path = tmp_path / "diagnostics.json"
    assert out_path.exists()

    reloaded = DiagnosticsReport.load(out_path)

    assert reloaded.gram_condition == pytest.approx(report.gram_condition)
    assert reloaded.dof_accounting == report.dof_accounting
    assert reloaded.manifest["airfoil"] == "2412"
    assert "git_sha" in reloaded.manifest
    assert "config_hash" in reloaded.manifest
    assert "timestamp_utc" in reloaded.manifest
    assert len(reloaded.iterations) == len(report.iterations) == 4
    for orig, back in zip(report.iterations, reloaded.iterations, strict=True):
        assert orig.it == back.it
        assert orig.R_norm == pytest.approx(back.R_norm)
        assert orig.T_norm == pytest.approx(back.T_norm)
        assert orig.G_norm == pytest.approx(back.G_norm)
        if orig.transition_xt is not None:
            assert tuple(orig.transition_xt) == tuple(back.transition_xt)
        else:
            assert back.transition_xt is None
        assert orig.extra == back.extra
    assert reloaded.convergence_order == pytest.approx(report.convergence_order)


def test_finalize_manifest_has_required_fields(tmp_path):
    diag = NewtonDiagnostics(config=CFG)
    diag.record_iteration(0, R_norm=1.0, T_norm=1.0, G_norm=1.0)
    report = diag.finalize(tmp_path, run_manifest={"foo": "bar"})
    for key in ("git_sha", "config_hash", "timestamp_utc", "foo"):
        assert key in report.manifest


# --------------------------------------------------------------------------- #
# D-6: convergence order estimator
# --------------------------------------------------------------------------- #


def test_convergence_order_quadratic_sequence():
    diag = NewtonDiagnostics(config=CFG)
    # e_{k+1} = e_k^2, e0 = 0.1 -> exactly quadratic tail.
    e = 0.1
    errors = []
    for _ in range(5):
        errors.append(e)
        e = e**2
    for it, err in enumerate(errors):
        diag.record_iteration(it, R_norm=err, T_norm=0.0, G_norm=0.0)

    p = diag.convergence_order_estimate()
    assert p == pytest.approx(2.0, abs=1e-6)


def test_convergence_order_linear_sequence():
    diag = NewtonDiagnostics(config=CFG)
    r = 0.3
    e0 = 1.0
    for it in range(5):
        diag.record_iteration(it, R_norm=e0 * r**it, T_norm=0.0, G_norm=0.0)

    p = diag.convergence_order_estimate()
    assert p == pytest.approx(1.0, abs=1e-6)


def test_convergence_order_short_history_returns_none():
    diag = NewtonDiagnostics(config=CFG)
    diag.record_iteration(0, R_norm=1.0, T_norm=0.0, G_norm=0.0)
    diag.record_iteration(1, R_norm=0.5, T_norm=0.0, G_norm=0.0)
    assert diag.convergence_order_estimate() is None

    # Empty history too.
    diag2 = NewtonDiagnostics(config=CFG)
    assert diag2.convergence_order_estimate() is None


def test_convergence_order_excludes_floor():
    diag = NewtonDiagnostics(config=CFG)
    # Residual bottoms out at the solver floor; the ratio there is meaningless
    # and must be excluded via `floor`.
    r_norms = [1e-1, 1e-2, 1e-4, 1e-8, 1e-16, 1e-16, 1e-16]
    for it, r in enumerate(r_norms):
        diag.record_iteration(it, R_norm=r, T_norm=0.0, G_norm=0.0)

    p_no_floor = diag.convergence_order_estimate()
    p_floored = diag.convergence_order_estimate(floor=1e-15)
    # Without excluding the floor, the last 3 (all == 1e-16) give a degenerate ratio.
    assert p_no_floor is None
    # With the floor excluded, the true quadratic tail (1e-2, 1e-4, 1e-8, ... wait 1e-8->1e-16
    # is also quadratic) is recovered.
    assert p_floored == pytest.approx(2.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# D-2: rank / condition detection
# --------------------------------------------------------------------------- #


def test_d2_rank_detects_full_rank_matrix(tmp_path):
    diag = NewtonDiagnostics(config=CFG)
    rng = np.random.default_rng(0)
    J = rng.standard_normal((10, 10))
    record = diag.record_iteration(0, R_norm=1.0, T_norm=1.0, G_norm=1.0, jacobian=J)
    assert record.rank_J == 10
    assert record.cond_J is not None and record.cond_J > 1.0


def test_d2_rank_detects_rank_deficient_matrix():
    diag = NewtonDiagnostics(config=CFG)
    rng = np.random.default_rng(1)
    base = rng.standard_normal((10, 6))
    # Deliberately rank-deficient: 10x10 built from a 10x6 factor times a 6x10 factor.
    J = base @ rng.standard_normal((6, 10))
    record = diag.record_iteration(0, R_norm=1.0, T_norm=1.0, G_norm=1.0, jacobian=J)
    assert record.rank_J == 6
    assert record.cond_J is not None and record.cond_J > 1e6


def test_d2_disabled_when_compute_expensive_false():
    diag = NewtonDiagnostics(config=CFG, compute_expensive=False)
    rng = np.random.default_rng(2)
    J = rng.standard_normal((5, 5))
    record = diag.record_iteration(0, R_norm=1.0, T_norm=1.0, G_norm=1.0, jacobian=J)
    assert record.rank_J is None
    assert record.cond_J is None


# --------------------------------------------------------------------------- #
# D-4: row-norm profile
# --------------------------------------------------------------------------- #


def test_d4_row_norm_profile_shows_nose_spike():
    diag = NewtonDiagnostics(config=CFG)
    n_rows = 50
    x_stations = np.linspace(0.0, 1.0, n_rows)
    # Synthetic dR_dA with a deliberate spike near x/c = 0 (the nose), tapering off.
    n_cols = 8
    rng = np.random.default_rng(3)
    base = 0.01 * rng.standard_normal((n_rows, n_cols))
    spike_row = 0
    base[spike_row, :] += 100.0  # nose spike

    record = diag.record_iteration(
        0, R_norm=1.0, T_norm=1.0, G_norm=1.0, dR_dA=base, x_stations=x_stations
    )
    assert record.dR_dA_row_norms is not None
    row_norms = np.asarray(record.dR_dA_row_norms)
    assert row_norms.shape[0] == n_rows
    # The nose row's norm must dominate the rest of the profile.
    other_max = np.delete(row_norms, spike_row).max()
    assert row_norms[spike_row] > 10 * other_max


# --------------------------------------------------------------------------- #
# Figure builders — structural smoke tests only
# --------------------------------------------------------------------------- #


def _sample_report(tmp_path) -> DiagnosticsReport:
    diag = NewtonDiagnostics(config=CFG)
    diag.record_static(gram_condition=1e5, dof_accounting={"n_A": 18, "M": 10, "K": 9})
    n_rows = 20
    x_stations = np.linspace(0.0, 1.0, n_rows)
    for it in range(5):
        dR_dA = 0.01 * np.ones((n_rows, 4))
        dR_dA[0, :] += 10.0 * (5 - it)
        diag.record_iteration(
            it,
            R_norm=10.0 ** (-2 * it - 1),
            T_norm=10.0 ** (-it - 1),
            G_norm=1e-12,
            dR_dA=dR_dA,
            x_stations=x_stations,
            transition_xt=(0.05 + 0.001 * it, 0.06),
        )
    return diag.finalize(tmp_path, run_manifest={"airfoil": "test"})


def test_fig_d1_residuals_builds_figure(tmp_path):
    report = _sample_report(tmp_path)
    fig = fig_d1_residuals(report)
    assert isinstance(fig, Figure)
    assert len(fig.axes) == 1


def test_fig_d4_row_norm_profile_builds_figure(tmp_path):
    report = _sample_report(tmp_path)
    fig = fig_d4_row_norm_profile(report)
    assert isinstance(fig, Figure)
    assert len(fig.axes) == 1


def test_fig_d5_transition_history_builds_figure(tmp_path):
    report = _sample_report(tmp_path)
    fig = fig_d5_transition_history(report)
    assert isinstance(fig, Figure)


def test_fig_d6_convergence_builds_figure(tmp_path):
    report = _sample_report(tmp_path)
    fig = fig_d6_convergence(report)
    assert isinstance(fig, Figure)
    assert "D-6" in fig.axes[0].get_title()


# --------------------------------------------------------------------------- #
# Config-driven
# --------------------------------------------------------------------------- #


def test_diagnostics_config_present_and_defaults():
    assert CFG.diagnostics.compute_expensive is True
    assert CFG.diagnostics.dense_rank_max_dim >= 1


def test_dense_rank_max_dim_gates_dense_svd():
    diag = NewtonDiagnostics(config=CFG, dense_rank_max_dim=3)
    rng = np.random.default_rng(4)
    J = rng.standard_normal((10, 10))  # bigger than dense_rank_max_dim=3
    record = diag.record_iteration(0, R_norm=1.0, T_norm=1.0, G_norm=1.0, jacobian=J)
    # Exact rank is skipped above dense_rank_max_dim; only an estimate is reported.
    assert record.rank_J is None
    assert record.cond_J is not None
