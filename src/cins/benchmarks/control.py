"""H2 control (baseline): nested ``scipy.optimize.least_squares`` over full
viscous mfoil solves (dossier §7.9 last ablation row, STATS_PROTOCOL H2).

This is the "how many flow solves would a naive-but-competently-tuned
shooting method need" comparison the paper's headline flow-solve-count claim
needs to be credible. Unlike the monolithic solve (one linearized system per
Newton iteration, ~2*n_free residual *evaluations* per iteration, dossier
§7.6), every ``scipy.least_squares`` residual-function call here is one fresh
**converged nonlinear viscous flow solve** at a perturbed geometry — the
currency H2 compares is ``n_flow_solves_equivalent`` on both sides (not
``n_residual_evaluations``, which is monolithic-specific: the nested method
has no analogous cheap-FD-column concept, every "evaluation" IS a solve).

STATS_PROTOCOL's baseline-tuning requirement: the initial guess is the SAME
T4 pre-solve given to the monolithic method (``prepare_cell``'s ``a0``, when
``t8.init == "presolve"`` — run the control cell against a
``t8.init: presolve`` config), and the ``scipy.least_squares`` call signature
(method, x_scale, ftol/xtol/gtol, max_nfev) is recorded in the manifest, per
STATS_PROTOCOL's explicit documentation requirement.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import least_squares

from cins.config import CinsConfig
from cins.cst.geometry import coords_from_A
from cins.solver.mfoil_adapter import (
    make_mfoil,
    mfoil_module,
    release_transition,
    set_forced_transition,
)
from cins.solver.presolve import InviscidCpResult, interpolate_cp_to_stations

from .instrumentation import EvalCounters, instrument_evaluations
from .pipeline import PreparedCell, _make_manifest, prepare_cell

__all__ = ["ControlResult", "run_control"]

log = logging.getLogger(__name__)

_NONCONVERGENCE_PENALTY = 50.0  # bounded finite residual fill; keeps least_squares well-posed
_DEFAULT_MAX_NFEV = 300


@dataclass
class ControlResult:
    """H2 nested-baseline outcome, comparable field-for-field against the
    matching monolithic ``CellResult`` (same cell config, same target)."""

    cell_name: str
    manifest: dict[str, Any]
    scipy_call_signature: dict[str, Any]
    converged: bool
    scipy_success: bool
    scipy_status: int
    scipy_message: str
    n_flow_solves_equivalent: int  # == nfev (+1 for the shared prepare_cell target solves)
    n_nfev: int
    err_free_inf: float | None
    err_all_inf: float | None
    final_cost: float | None
    final_residual_inf: float | None
    wall_time_s: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _viscous_cp_at_A(
    A: np.ndarray, prep: PreparedCell, cfg: CinsConfig
) -> InviscidCpResult | None:
    """One fresh direct (re-paneled) viscous solve at coefficient vector A.

    Returns None if either the warm-start or the (optionally forced-trip)
    coupled solve fails to converge — the caller penalizes this rather than
    raising, so scipy sees a well-posed (if bad) residual and keeps searching.
    """
    n = prep.n
    Xc = coords_from_A(
        A[: n + 1], A[n + 1 :], prep.fit.zeta_T_upper, prep.fit.zeta_T_lower, prep.psi
    )
    # prepare_cell leaves the ADR-0003 shims installed process-wide; a fresh
    # instance's natural cold-start solve is INCONSISTENT under them (no-op
    # update_transition + onset residual vs a naturally-initialized turb
    # pattern) — verified empirically: every trial returned None, giving scipy
    # a constant penalty residual and an instant bogus "gtol success" at nfev=1.
    release_transition()
    m = make_mfoil(coords=Xc)
    m.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
    m.solve()
    if not m.glob.conv:
        return None
    if cfg.transition.mode == "forced":
        mod = mfoil_module()
        set_forced_transition(m, cfg.transition.xtr_upper, cfg.transition.xtr_lower)
        mod.solve_coupled(m)
        mod.calc_force(m)
        if not m.glob.conv:
            return None
    x = np.array(m.foil.x[0], dtype=float)
    # post.cp covers airfoil+wake in viscous mode; keep airfoil-only to match x
    # (fp/xp length mismatch crashed the v2 control run otherwise)
    cp = np.array(m.post.cp, dtype=float)[: m.foil.N]
    return InviscidCpResult(x=x, cp=cp, le_idx=int(np.argmin(x)))


def run_control(
    cfg: CinsConfig,
    *,
    cell_name: str = "control",
    config_path: str | Path | None = None,
    max_nfev: int = _DEFAULT_MAX_NFEV,
) -> ControlResult:
    """Run the nested scipy.least_squares baseline for one T8 cell.

    Expensive (dossier §7.9: "the headline claim is a count of flow solves");
    intended to be run ONCE, on the winning-configuration cell only (task
    scoping), not swept across the whole ablation matrix.
    """
    t0 = time.perf_counter()
    counters = EvalCounters()

    try:
        return _run_control_inner(cfg, cell_name, config_path, max_nfev, t0, counters)
    finally:
        release_transition()


def _run_control_inner(cfg, cell_name, config_path, max_nfev, t0, counters) -> ControlResult:
    with instrument_evaluations(counters):
        prep = prepare_cell(cfg, counters, cell_name=cell_name, config_path=config_path, t0=t0)
        if prep.early_failure is not None:
            ef = prep.early_failure
            return ControlResult(
                cell_name=cell_name, manifest=ef.manifest, scipy_call_signature={},
                converged=False, scipy_success=False, scipy_status=-1,
                scipy_message="prepare_cell failed before the nested solve started",
                n_flow_solves_equivalent=ef.n_flow_solves_equivalent, n_nfev=0,
                err_free_inf=None, err_all_inf=None, final_cost=None, final_residual_inf=None,
                wall_time_s=ef.wall_time_s, notes=ef.notes + [ef.dof_check_error or ""],
            )

        x0 = prep.a0[prep.free_idx].copy()
        a_star = prep.a_star
        template = prep.a0.copy()

        def residual_fn(x: np.ndarray) -> np.ndarray:
            A = template.copy()
            A[prep.free_idx] = x
            trial = _viscous_cp_at_A(A, prep, cfg)
            if trial is None:
                return np.full(len(prep.stations), _NONCONVERGENCE_PENALTY)
            cp_at_target_x = interpolate_cp_to_stations(trial, prep.target_cp_result)
            return cp_at_target_x[prep.stations] - prep.cp_target

        x_scale = np.maximum(np.abs(x0), 1e-3)
        call_sig = {
            "method": "lm" if len(prep.stations) >= len(x0) else "trf",
            "x_scale": "custom(|x0| floor 1e-3)",
            "ftol": 1e-8, "xtol": 1e-8, "gtol": 1e-8,
            "max_nfev": max_nfev,
        }
        log.info("control: nested least_squares n_free=%d n_targets=%d max_nfev=%d",
                  len(x0), len(prep.stations), max_nfev)
        result = least_squares(
            residual_fn, x0, method=call_sig["method"], x_scale=x_scale,
            ftol=1e-8, xtol=1e-8, gtol=1e-8, max_nfev=max_nfev,
        )

        a_final = template.copy()
        a_final[prep.free_idx] = result.x
        err_free = float(np.max(np.abs(result.x - a_star[prep.free_idx])))
        err_all = float(np.max(np.abs(a_final - a_star)))
        final_residual_inf = float(np.max(np.abs(result.fun))) if result.fun.size else None
        converged = bool(bool(result.success) and (final_residual_inf or 0.0) < 1.0)
        log.info(
            "control RESULT: success=%s status=%d nfev=%d err_free_inf=%.3e err_all_inf=%.3e",
            result.success, result.status, result.nfev, err_free, err_all,
        )

    manifest = _make_manifest(cfg, cell_name, config_path)
    manifest["scipy_call_signature"] = call_sig
    manifest["control_baseline"] = True
    return ControlResult(
        cell_name=cell_name, manifest=manifest, scipy_call_signature=call_sig,
        converged=converged, scipy_success=bool(result.success), scipy_status=int(result.status),
        scipy_message=str(result.message),
        n_flow_solves_equivalent=counters.n_flow_solves_equivalent,
        n_nfev=int(result.nfev), err_free_inf=err_free, err_all_inf=err_all,
        final_cost=float(result.cost), final_residual_inf=final_residual_inf,
        wall_time_s=time.perf_counter() - t0, notes=list(prep.notes),
    )
