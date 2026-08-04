"""Unit tests for T8 benchmark infrastructure (config overlay, manifest,
DOF-offset clean failure, evaluation-counter accounting).

Heavy mfoil solves are mocked throughout (tests/CLAUDE.md fast-test contract,
pyproject's ``-m 'not slow'`` default) — these tests exercise runner/pipeline
*logic*, not the physics. The one real end-to-end smoke run (winning
configuration, n=8) is a separate, manually-invoked check
(``experiments/run_t7.py`` / ``python -m cins.benchmarks run
configs/experiments/t8_n08_baseline.yaml``), not part of the fast suite.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import cins.benchmarks.instrumentation as instr
import cins.benchmarks.pipeline as pipeline
from cins.config import load_config
from cins.cst.fit import FitResult
from cins.solver.presolve import InviscidCpResult, SensitivityResult

EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "configs" / "experiments"


# --------------------------------------------------------------------------- #
# 1. config overlay correctness
# --------------------------------------------------------------------------- #


def test_t8_config_defaults_from_default_yaml():
    cfg = load_config()
    assert cfg.t8.airfoil == "2412"
    assert cfg.t8.station_selection == "qr_pivot"
    assert cfg.t8.init == "presolve"
    assert cfg.t8.alpha_free is False
    assert cfg.t8.dof_offset == 0


def test_t8_cell_overlay_merges_and_leaves_rest_default():
    cfg = load_config(EXPERIMENTS_DIR / "t8_dof_over.yaml")
    assert cfg.t8.dof_offset == 1
    # untouched fields keep configs/default.yaml's values
    assert cfg.cst.n_upper == 8
    assert cfg.transition.mode == "forced"
    assert cfg.t8.station_selection == "qr_pivot"


def test_t8_n_ablation_cell_overlay():
    cfg = load_config(EXPERIMENTS_DIR / "t8_n04.yaml")
    assert cfg.cst.n_upper == 4
    assert cfg.cst.n_lower == 4


def test_dof_offset_out_of_range_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("t8:\n  dof_offset: 2\n")
    with pytest.raises(Exception):
        load_config(p)


def test_all_experiment_cells_are_valid_configs():
    cells = sorted(EXPERIMENTS_DIR.glob("*.yaml"))
    assert len(cells) >= 10
    for cell in cells:
        cfg = load_config(cell)  # must not raise
        assert cfg.t8.dof_offset in (-1, 0, 1)


# --------------------------------------------------------------------------- #
# 2. manifest completeness
# --------------------------------------------------------------------------- #


def test_manifest_has_required_fields():
    cfg_path = EXPERIMENTS_DIR / "t8_n08_baseline.yaml"
    cfg = load_config(cfg_path)
    manifest = pipeline._make_manifest(cfg, "t8_n08_baseline", cfg_path)
    for key in ("cell_name", "git_sha", "config_hash", "config_path", "seed",
                "timestamp", "t8_factors", "cst", "transition_mode"):
        assert key in manifest, f"manifest missing {key!r}"
    assert manifest["seed"] == cfg.experiment.seed
    assert manifest["config_hash"] == cfg.config_hash()
    assert manifest["git_sha"] != ""  # "unknown" is an acceptable fallback, empty is not


# --------------------------------------------------------------------------- #
# 3. dof_offset clean-failure capture (FM-1) — heavy solve mocked
# --------------------------------------------------------------------------- #


class _FakePost:
    def __init__(self, n_stations: int):
        self.cl = 0.5
        self.cd = 0.01
        self.cp = np.linspace(-1.0, 1.0, n_stations)


class _FakeFoil:
    def __init__(self, n_stations: int):
        self.x = np.linspace(0.0, 1.0, n_stations).reshape(1, -1)


class _FakeMfoil:
    """Minimal stand-in for a converged mfoil instance."""

    def __init__(self, n_stations: int = 50):
        self.geom = SimpleNamespace(xpoint=np.zeros((2, n_stations)))
        self.glob = SimpleNamespace(conv=True)
        self.post = _FakePost(n_stations)
        self.foil = _FakeFoil(n_stations)
        self.oper = SimpleNamespace(alpha=2.0)

    def setoper(self, alpha=None, Re=None):
        pass

    def solve(self):
        self.glob.conv = True


class _FakeVendorModule:
    def solve_coupled(self, m):
        m.glob.conv = True

    def calc_force(self, m):
        pass


N_STATIONS = 50


def _patch_heavy_solve(monkeypatch, n=4):
    """Replace every mfoil-touching call in pipeline.prepare_cell with cheap
    fakes so DOF-accounting/station-selection *logic* can be exercised
    without a real flow solve."""
    n_a = 2 * (n + 1)
    fake_fit = FitResult(
        A_upper=np.full(n + 1, 0.1), A_lower=-np.full(n + 1, 0.1),
        zeta_T_upper=0.0, zeta_T_lower=0.0, n=n, N1=0.5, N2=1.0,
        rms=1e-5, gram_condition=1.0,
    )
    monkeypatch.setattr(pipeline, "make_mfoil", lambda *a, **k: _FakeMfoil(N_STATIONS))
    monkeypatch.setattr(pipeline, "mfoil_module", lambda: _FakeVendorModule())
    monkeypatch.setattr(pipeline, "fit_cst", lambda *a, **k: fake_fit)
    monkeypatch.setattr(pipeline, "set_forced_transition", lambda *a, **k: None)
    # apply_geometry does a real (heavy, mfoil-internals-dependent) panel rebuild;
    # a no-op is sufficient for exercising DOF-accounting/station-selection logic,
    # and keeps _FakeMfoil's geometry self-consistent (x_mismatch guard stays 0).
    monkeypatch.setattr(pipeline, "apply_geometry", lambda *a, **k: None)

    def fake_solve_inviscid_cp(*a, **k):
        return InviscidCpResult(
            x=np.linspace(0.0, 1.0, N_STATIONS), cp=np.zeros(N_STATIONS), le_idx=0
        )

    monkeypatch.setattr(pipeline, "solve_inviscid_cp", fake_solve_inviscid_cp)

    rng = np.random.default_rng(0)
    sens = SensitivityResult(
        M=rng.standard_normal((N_STATIONS, n_a)),
        Cp0=np.zeros(N_STATIONS),
        x_stations=np.linspace(0.0, 1.0, N_STATIONS),
        baseline=fake_solve_inviscid_cp(),
    )

    def fake_presolve(cp_target, au0, al0, ztu, ztl, psi, rows, cfg):
        A = np.concatenate([au0, al0])
        return SimpleNamespace(
            A=A, delta_A=np.zeros_like(A), realisability=0.01, sensitivity=sens
        )

    monkeypatch.setattr(pipeline, "presolve", fake_presolve)
    monkeypatch.setattr(pipeline, "build_sensitivity_matrix", lambda *a, **k: sens)
    return sens


def test_dof_offset_plus_one_fails_cleanly_not_crash(monkeypatch):
    cfg = load_config(EXPERIMENTS_DIR / "t8_dof_over.yaml").model_copy(deep=True)
    cfg = cfg.model_copy(update={"cst": cfg.cst.model_copy(update={"n_upper": 4, "n_lower": 4})})
    _patch_heavy_solve(monkeypatch, n=4)

    counters = instr.EvalCounters()
    prep = pipeline.prepare_cell(cfg, counters, cell_name="t8_dof_over_test")

    assert prep.early_failure is not None
    assert prep.early_failure.converged is False
    assert prep.early_failure.dof_check_error is not None
    assert "not square" in prep.early_failure.dof_check_error


def test_dof_offset_minus_one_fails_cleanly_not_crash(monkeypatch):
    cfg = load_config(EXPERIMENTS_DIR / "t8_dof_under.yaml").model_copy(deep=True)
    cfg = cfg.model_copy(update={"cst": cfg.cst.model_copy(update={"n_upper": 4, "n_lower": 4})})
    _patch_heavy_solve(monkeypatch, n=4)

    counters = instr.EvalCounters()
    prep = pipeline.prepare_cell(cfg, counters, cell_name="t8_dof_under_test")

    assert prep.early_failure is not None
    assert prep.early_failure.dof_check_error is not None


def test_dof_offset_zero_passes_the_square_check(monkeypatch):
    """Sanity: the SAME mocked pipeline with dof_offset=0 must NOT hit the
    DOF-check early-exit (proves the +-1 tests above fail because of the
    offset, not because of the mocking)."""
    cfg = load_config(EXPERIMENTS_DIR / "t8_n08_baseline.yaml").model_copy(deep=True)
    cfg = cfg.model_copy(update={"cst": cfg.cst.model_copy(update={"n_upper": 4, "n_lower": 4})})
    _patch_heavy_solve(monkeypatch, n=4)

    counters = instr.EvalCounters()
    prep = pipeline.prepare_cell(cfg, counters, cell_name="t8_n04_square_test")

    assert prep.early_failure is None
    assert prep.stations is not None
    assert len(prep.cp_target) == len(prep.stations)


# --------------------------------------------------------------------------- #
# 3b. "uiuc:<name>" airfoil resolution (STATS_PROTOCOL §3.3 panel)
# --------------------------------------------------------------------------- #


def test_uiuc_prefixed_airfoil_resolves_through_loader_not_naca(monkeypatch):
    """cfg.t8.airfoil = "uiuc:ag16" must route A* fitting through
    cins.cst.io.load_airfoil_dat, and must NOT call make_mfoil(naca=...)
    for the reference-coefficient step (that call is naca-only)."""
    n = 4
    sens = _patch_heavy_solve(monkeypatch, n=n)  # noqa: F841 (keeps mocks consistent)

    calls: list[Path] = []
    real_uiuc_path = pipeline.uiuc_dat_path("ag16")

    def spy_loader(path):
        calls.append(Path(path))
        # real load, so downstream fit_cst (mocked) still gets a plausible X
        from cins.cst.io import load_airfoil_dat as _real_load

        return _real_load(path)

    monkeypatch.setattr(pipeline, "load_airfoil_dat", spy_loader)

    naca_calls: list[tuple] = []
    orig_make_mfoil = pipeline.make_mfoil

    def spy_make_mfoil(*a, **k):
        if k.get("naca") is not None or (a and isinstance(a[0], str)):
            naca_calls.append((a, k))
        return orig_make_mfoil(*a, **k)

    monkeypatch.setattr(pipeline, "make_mfoil", spy_make_mfoil)

    cfg = load_config(EXPERIMENTS_DIR / "t8_n08_baseline.yaml").model_copy(deep=True)
    cfg = cfg.model_copy(
        update={
            "cst": cfg.cst.model_copy(update={"n_upper": n, "n_lower": n}),
            "t8": cfg.t8.model_copy(update={"airfoil": "uiuc:ag16"}),
        }
    )

    counters = instr.EvalCounters()
    prep = pipeline.prepare_cell(cfg, counters, cell_name="t8_uiuc_test")

    assert calls == [real_uiuc_path]
    assert naca_calls == []  # no naca-branch make_mfoil call for A* fitting
    assert prep.early_failure is None


# --------------------------------------------------------------------------- #
# 4. evaluation-counter accounting (H2 currency) — mocked vendor entry points
# --------------------------------------------------------------------------- #


def test_instrument_evaluations_counts_and_restores(monkeypatch):
    class FakeVendor:
        def solve_coupled(self, m):
            return "coupled"

        def solve_inviscid(self, m):
            return "inviscid"

    fake_vendor = FakeVendor()
    orig_solve_coupled = fake_vendor.solve_coupled
    orig_solve_inviscid = fake_vendor.solve_inviscid

    def fake_flow_residual(m):
        return "residual"

    # what instrument_evaluations must restore TO is its own __enter__-time
    # snapshot (i.e. these monkeypatched fakes), not whatever flow_residual
    # was before this test ever ran.
    monkeypatch.setattr(instr._adapter_mod, "mfoil_module", lambda: fake_vendor)
    monkeypatch.setattr(instr._geom_mod, "flow_residual", fake_flow_residual)
    monkeypatch.setattr(instr._newton_mod, "flow_residual", fake_flow_residual)

    counters = instr.EvalCounters()
    with instr.instrument_evaluations(counters):
        # dR_dA_fd-style bare-name lookup is simulated by calling the module
        # attribute directly, exactly how geometry_update.dR_dA_fd does.
        instr._geom_mod.flow_residual(None)
        instr._geom_mod.flow_residual(None)
        instr._newton_mod.flow_residual(None)
        fake_vendor.solve_coupled(None)
        fake_vendor.solve_inviscid(None)
        fake_vendor.solve_inviscid(None)

    assert counters.n_residual_evaluations == 3
    assert counters.n_flow_solves_equivalent == 3
    breakdown = counters.as_dict()["breakdown"]
    assert breakdown["flow_residual"] == 3
    assert breakdown["solve_coupled"] == 1
    assert breakdown["solve_inviscid"] == 2

    # patches restored on exit — no leakage into later tests/production code
    assert fake_vendor.solve_coupled == orig_solve_coupled
    assert fake_vendor.solve_inviscid == orig_solve_inviscid
    assert instr._geom_mod.flow_residual is fake_flow_residual
    assert instr._newton_mod.flow_residual is fake_flow_residual


def test_instrument_evaluations_restores_on_exception(monkeypatch):
    class FakeVendor:
        def solve_coupled(self, m):
            pass

        def solve_inviscid(self, m):
            pass

    fake_vendor = FakeVendor()
    monkeypatch.setattr(instr._adapter_mod, "mfoil_module", lambda: fake_vendor)
    orig = instr._geom_mod.flow_residual

    counters = instr.EvalCounters()
    with pytest.raises(RuntimeError):
        with instr.instrument_evaluations(counters):
            raise RuntimeError("boom")

    assert instr._geom_mod.flow_residual is orig
