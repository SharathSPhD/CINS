"""T8 ablation-cell pipeline (STATS_PROTOCOL, dossier §7.9) — the T7 falsifiable
test (``experiments/run_t7.py``), parameterized over the ablation factors so one
function drives every cell in the matrix.

``run_pipeline`` is a straight refactor of ``experiments/run_t7.py``'s ``main()``:
every comment there documenting WHY a step exists (prescribed-LE pinning, the
alpha-camber equivalence family, the T4 basin-selection necessity, the QR-pivoted
station selection, joint under-relaxation, release-and-verify) still applies here
verbatim — see that module and the ``t7-winning-configuration`` memory note for
the full rationale. This module adds only the ablation branching (T8 factors)
and evaluation-count instrumentation (H2 currency, ``instrumentation.py``)
around the same sequence of steps.

``prepare_cell`` factors out everything UP TO (but not including) the
monolithic Newton solve — target generation, station selection, T4 pre-solve,
the perturbed/random initial guess — into one function shared by
``run_pipeline`` (the monolithic path) and ``control.py`` (the nested
``scipy.least_squares`` baseline, STATS_PROTOCOL H2). This is not just DRY:
H2's paired comparison is only valid if both methods see the *identical*
target Cp, station set, and free-coefficient set, and a single shared
preparation function is what guarantees that by construction rather than by
two independently-maintained copies staying in sync.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.linalg import qr as _qr

from cins.config import REPO_ROOT, CinsConfig
from cins.cst.constraints import shared_le_radius_row
from cins.cst.fit import FitResult, fit_cst
from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.geometry_update import apply_geometry
from cins.solver.mfoil_adapter import (
    make_mfoil,
    mfoil_module,
    release_transition,
    set_forced_transition,
)
from cins.solver.newton import InverseProblem, assert_square, select_target_stations, solve_inverse
from cins.solver.presolve import (
    InviscidCpResult,
    build_sensitivity_matrix,
    interpolate_cp_to_stations,
    presolve,
    solve_inviscid_cp,
)

from .instrumentation import EvalCounters, instrument_evaluations

__all__ = ["CellResult", "PreparedCell", "prepare_cell", "run_pipeline"]

log = logging.getLogger(__name__)

_PSI_NPOINT = 160  # CST sampling grid resolution (matches experiments/run_t7.py)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


@dataclass
class CellResult:
    """One T8 ablation cell's outcome — the unit written to
    ``experiments/results/t8/<cellname>/result.json`` (STATS_PROTOCOL §1, §7)."""

    cell_name: str
    manifest: dict[str, Any]
    converged: bool
    iterations: int
    err_free_inf: float | None
    err_all_inf: float | None
    residual_history: list[float]
    convergence_order: float | None
    n_residual_evaluations: int
    n_flow_solves_equivalent: int
    release_verify: dict[str, Any] | None
    realisability: float | None
    model_gap: float | None
    submap_cond: float | None
    wall_time_s: float
    dof_check_error: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CellResult":
        return cls(**d)


def _make_manifest(
    cfg: CinsConfig, cell_name: str, config_path: str | Path | None
) -> dict[str, Any]:
    return {
        "cell_name": cell_name,
        "git_sha": _git_sha(),
        "config_hash": cfg.config_hash(),
        "config_path": str(config_path) if config_path is not None else None,
        "seed": cfg.experiment.seed,
        "timestamp": datetime.now(UTC).isoformat(),
        "t8_factors": cfg.t8.model_dump(),
        "cst": {
            "n_upper": cfg.cst.n_upper, "n_lower": cfg.cst.n_lower,
            "le_treatment": cfg.cst.le_treatment,
        },
        "transition_mode": cfg.transition.mode,
    }


def _early_result(
    cfg: CinsConfig, cell_name: str, config_path, t0: float,
    *, dof_check_error: str | None = None, notes: list[str] | None = None,
    counters: EvalCounters | None = None,
) -> CellResult:
    counters = counters or EvalCounters()
    return CellResult(
        cell_name=cell_name,
        manifest=_make_manifest(cfg, cell_name, config_path),
        converged=False,
        iterations=0,
        err_free_inf=None,
        err_all_inf=None,
        residual_history=[],
        convergence_order=None,
        n_residual_evaluations=counters.n_residual_evaluations,
        n_flow_solves_equivalent=counters.n_flow_solves_equivalent,
        release_verify=None,
        realisability=None,
        model_gap=None,
        submap_cond=None,
        wall_time_s=time.perf_counter() - t0,
        dof_check_error=dof_check_error,
        notes=notes or [],
    )


@dataclass
class PreparedCell:
    """Everything shared by the monolithic (``run_pipeline``) and nested
    (``control.run_control``) solves: identical target Cp, station set, and
    free-coefficient set (STATS_PROTOCOL H2 paired-comparison requirement).

    ``early_failure`` is set (and every other field left at its default) when
    preparation itself hit a designed clean-failure path (FM-1 dof_offset, a
    non-converging direct/perturbed solve, the x-correspondence guard) — the
    caller must check it before using the rest of the dataclass.
    """

    m: Any = None  # mfoil instance, converged viscous state AT a0
    fit: FitResult | None = None
    a_star: np.ndarray | None = None
    a0: np.ndarray | None = None
    free_idx: np.ndarray | None = None
    G: np.ndarray | None = None
    b: np.ndarray | None = None
    stations: np.ndarray | None = None
    cp_target: np.ndarray | None = None
    target_cp_result: InviscidCpResult | None = None  # (x, cp, le_idx) at TARGET geometry's
    # own paneling — control.py's nested baseline re-panels independently per trial and must
    # interpolate onto these x-locations (presolve.py's station-matching problem, applies here
    # identically) to compare against the SAME cp_target the monolithic solve used.
    n: int = 0
    psi: np.ndarray | None = None
    nat_cl: float = 0.0
    nat_cd: float = 0.0
    realisability: float | None = None
    model_gap: float | None = None
    submap_cond: float | None = None
    notes: list[str] = field(default_factory=list)
    early_failure: CellResult | None = None


def prepare_cell(
    cfg: CinsConfig,
    counters: EvalCounters,
    *,
    cell_name: str = "cell",
    config_path: str | Path | None = None,
    t0: float | None = None,
) -> PreparedCell:
    """Steps 1-6 of the T7 pipeline (target generation through station
    selection + convergence at A0), shared by the monolithic and nested
    control solves. Must be called inside an open ``instrument_evaluations``
    context so the flow solves/residual evals performed here are counted.
    """
    t0 = t0 if t0 is not None else time.perf_counter()
    notes: list[str] = []
    mod = mfoil_module()

    if cfg.cst.n_upper != cfg.cst.n_lower:
        notes.append(
            f"n_upper={cfg.cst.n_upper} != n_lower={cfg.cst.n_lower}; pipeline assumes "
            "symmetric order (matches experiments/run_t7.py)."
        )
    n = cfg.cst.n_upper
    psi = cosine_spacing(_PSI_NPOINT)

    # --- 1. reference coefficients A* ----------------------------------------
    m_ref = make_mfoil(naca=cfg.t8.airfoil)
    X = m_ref.geom.xpoint
    fit = fit_cst(X[0], X[1], n)
    a_star = np.concatenate([fit.A_upper, fit.A_lower])
    log.info("A* fitted: airfoil=%s n=%d rms=%.2e", cfg.t8.airfoil, n, fit.rms)

    # --- 2. target Cp ----------------------------------------------------------
    Xc = coords_from_A(fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi)
    m = make_mfoil(coords=Xc)
    m.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
    m.solve()
    if not m.glob.conv:
        return PreparedCell(early_failure=_early_result(
            cfg, cell_name, config_path, t0,
            notes=["direct (natural) target solve failed to converge"], counters=counters))
    nat_cl, nat_cd = float(m.post.cl), float(m.post.cd)
    x_target_nodes = m.foil.x[0].copy()

    forced = cfg.transition.mode == "forced"
    if forced:
        set_forced_transition(m, cfg.transition.xtr_upper, cfg.transition.xtr_lower)
        mod.solve_coupled(m)
        if not m.glob.conv:
            return PreparedCell(early_failure=_early_result(
                cfg, cell_name, config_path, t0,
                notes=["forced-trip target solve failed to converge"], counters=counters))
        mod.calc_force(m)
        log.info("target generated (tripped): cl=%.4f cd=%.5f", m.post.cl, m.post.cd)
    else:
        log.info("target generated (free transition): cl=%.4f cd=%.5f", nat_cl, nat_cd)
    cp_ref = np.asarray(m.post.cp).copy()

    # --- 3. free coefficients / constraints -------------------------------------
    n_a = len(a_star)
    if cfg.cst.le_treatment == "prescribed":
        fixed = [0, n + 1]
        free_idx = np.array([i for i in range(n_a) if i not in fixed])
        G = np.zeros((0, n_a))
        b = np.zeros(0)
    else:
        free_idx = np.arange(n_a)
        g_row, _ = shared_le_radius_row(n, n)
        G = g_row.reshape(1, -1)
        b = np.array([float(g_row @ a_star)])
    n_alpha = 1 if cfg.t8.alpha_free else 0
    n_targets_required = len(free_idx) - G.shape[0] + n_alpha

    # --- 4. initial guess A0 -----------------------------------------------------
    rng = np.random.default_rng(cfg.experiment.seed)
    a0 = a_star.copy()
    if cfg.t8.init == "random":
        a0[free_idx] = rng.uniform(-0.6, 0.6, size=len(free_idx))
        notes.append("init=random: A0 drawn independent of A* (dossier §7.9 init ablation)")
    else:
        a0[free_idx] = a_star[free_idx] * (
            1.0 + cfg.t8.n_perturb_frac * rng.standard_normal(len(free_idx))
        )
    log.info("init=%s ||A0-A*||_inf = %.3e", cfg.t8.init, np.max(np.abs(a0 - a_star)))

    realisability = model_gap = None
    if cfg.t8.init == "presolve":
        target_res = solve_inviscid_cp(
            fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
        )
        for it_ps in range(2):
            base_res = solve_inviscid_cp(
                a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
            )
            cp_t_at_a0 = interpolate_cp_to_stations(target_res, base_res)
            ps = presolve(
                cp_t_at_a0, a0[: n + 1], a0[n + 1 :],
                fit.zeta_T_upper, fit.zeta_T_lower, psi, [], cfg,
            )
            a0 = np.asarray(ps.A, dtype=float)
            a0[0], a0[n + 1] = a_star[0], a_star[n + 1]
            cp_visc_at_ps = np.asarray(cp_ref[: len(ps.sensitivity.x_stations)])
            model_gap = float(
                np.linalg.norm(
                    ps.sensitivity.M @ ps.delta_A - (cp_visc_at_ps - ps.sensitivity.Cp0)
                ) / np.linalg.norm(cp_visc_at_ps)
            )
            realisability = ps.realisability
            log.info(
                "presolve pass %d: ||A-A*||_inf=%.3e realisability=%.4f model_gap=%.4f",
                it_ps + 1, np.max(np.abs(a0 - a_star)), realisability, model_gap,
            )
    else:
        notes.append(f"init={cfg.t8.init}: T4 pre-solve skipped by design (ablation factor)")

    # --- 5. station selection ------------------------------------------------------
    n_pick = n_targets_required + cfg.t8.dof_offset
    sens = build_sensitivity_matrix(
        a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
    )
    le_frac = cfg.cst.prescribed_le_fraction if cfg.cst.le_treatment == "prescribed" else 0.0

    if cfg.t8.station_selection == "qr_pivot":
        x_sens = np.asarray(sens.x_stations)
        cand = np.nonzero(x_sens >= le_frac)[0]
        if len(cand) < n_pick:
            return PreparedCell(early_failure=_early_result(
                cfg, cell_name, config_path, t0,
                notes=[f"only {len(cand)} candidate stations for {n_pick} requested"],
                counters=counters))
        m_cand = sens.M[cand][:, free_idx]
        _, _, piv = _qr(m_cand.T, pivoting=True)
        stations = np.sort(cand[piv[:n_pick]])
    else:  # "even"
        stations = select_target_stations(m, cfg, n_pick)

    sub = sens.M[stations][:, free_idx]
    submap_cond = float(np.linalg.cond(sub)) if sub.size else None
    log.info("station selection (%s): n_pick=%d cond(submap)=%s",
              cfg.t8.station_selection, n_pick, submap_cond)

    # --- 5b. FM-1 DOF check (must fail cleanly, not crash) --------------------------
    try:
        assert_square(len(free_idx), len(stations), G.shape[0], alpha_free=cfg.t8.alpha_free)
    except ValueError as e:
        log.info("DOF check failed as designed (dof_offset=%+d): %s", cfg.t8.dof_offset, e)
        return PreparedCell(early_failure=_early_result(
            cfg, cell_name, config_path, t0, dof_check_error=str(e),
            notes=[f"FM-1 ablation: dof_offset={cfg.t8.dof_offset:+d} deliberately mis-squares "
                   "the extended system; caught cleanly per STATS_PROTOCOL §4"],
            counters=counters))
    cp_target = cp_ref[stations]

    # --- 6. converge flow at the perturbed/random start ------------------------------
    apply_geometry(m, a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi)
    mod.solve_coupled(m)
    if not m.glob.conv:
        return PreparedCell(early_failure=_early_result(
            cfg, cell_name, config_path, t0,
            notes=[f"init={cfg.t8.init}: flow solve at A0 failed to converge"],
            counters=counters))

    x_mismatch = float(np.max(np.abs(m.foil.x[0, stations] - x_target_nodes[stations])))
    if x_mismatch >= 2e-5:
        # Re-map each station to the nearest-x node on the same surface (local
        # ±5-index search keeps upper/lower sides distinct). The identity map
        # only holds when re-paneling barely moves nodes (winning config); at
        # other n / larger perturbations the drift exceeded the guard (v2 sweep:
        # 2.4e-5..2e-4 on n06/n12/init_perturbed) — remap instead of failing.
        # Pairing matters: station_idx addresses CURRENT-geometry nodes (where the
        # solver reads Cp); the target value stays the TARGET geometry's Cp at the
        # originally selected station. Dedupe keeps the first pair per node.
        n_foil = m.foil.N
        pairs: dict[int, float] = {}
        for s_idx in stations:
            lo, hi = max(0, s_idx - 5), min(n_foil, s_idx + 6)
            j = lo + int(np.argmin(np.abs(m.foil.x[0, lo:hi] - x_target_nodes[s_idx])))
            pairs.setdefault(j, float(cp_ref[s_idx]))
        if len(pairs) < n_pick:
            return PreparedCell(early_failure=_early_result(
                cfg, cell_name, config_path, t0,
                notes=[f"station remap collapsed {n_pick}->{len(pairs)} stations"],
                counters=counters))
        order = np.argsort(list(pairs.keys()))
        stations = np.array(list(pairs.keys()))[order]
        cp_target = np.array(list(pairs.values()))[order]
        x_mismatch = float(np.max(np.abs(
            m.foil.x[0, stations]
            - np.array([x_target_nodes[s] for s in pairs.keys()])[order]
        )))
        notes.append(f"stations remapped by nearest-x; residual max|dx/c|={x_mismatch:.2e}")
        if x_mismatch >= 1e-3:
            return PreparedCell(early_failure=_early_result(
                cfg, cell_name, config_path, t0,
                notes=[f"station x-correspondence unrecoverable: {x_mismatch:.2e} >= 1e-3"],
                counters=counters))

    target_cp_result = InviscidCpResult(
        x=x_target_nodes, cp=cp_ref, le_idx=int(np.argmin(x_target_nodes))
    )
    return PreparedCell(
        m=m, fit=fit, a_star=a_star, a0=a0, free_idx=free_idx, G=G, b=b,
        stations=stations, cp_target=cp_target, target_cp_result=target_cp_result, n=n, psi=psi,
        nat_cl=nat_cl, nat_cd=nat_cd, realisability=realisability, model_gap=model_gap,
        submap_cond=submap_cond, notes=notes,
    )


def run_pipeline(
    cfg: CinsConfig,
    *,
    cell_name: str = "cell",
    config_path: str | Path | None = None,
    run_dir: str | Path | None = None,
) -> CellResult:
    """Run the T7-style monolithic inverse pipeline for one T8 ablation cell.

    Parameterized entirely by ``cfg`` (``cfg.cst``, ``cfg.transition``,
    ``cfg.t8`` — see ``configs/default.yaml``'s ``t8:`` section for the field
    list and ``src/cins/config.py::T8Config`` for the ablation-factor
    semantics). Returns a fully-populated ``CellResult`` even on a designed
    "clean failure" (FM-1 dof_offset != 0, non-convergence, guard failures):
    those paths are caught explicitly in ``prepare_cell`` and reported via
    ``CellResult``, never raised out of this function.
    """
    t0 = time.perf_counter()
    counters = EvalCounters()

    # The forced-transition shims installed inside prepare_cell are PROCESS-GLOBAL
    # (ADR-0003); every exit path must release them or subsequent cells in the same
    # process are poisoned (observed: sweep cells after the dof_* early-failures all
    # died at target generation). Belt: this try/finally. Suspenders: runner.sweep
    # isolates each cell in a subprocess.
    try:
        return _run_pipeline_inner(cfg, cell_name, config_path, run_dir, t0, counters)
    finally:
        release_transition()


def _run_pipeline_inner(cfg, cell_name, config_path, run_dir, t0, counters) -> CellResult:
    with instrument_evaluations(counters):
        prep = prepare_cell(cfg, counters, cell_name=cell_name, config_path=config_path, t0=t0)
        if prep.early_failure is not None:
            return prep.early_failure

        prob = InverseProblem(
            cp_target=prep.cp_target, station_idx=prep.stations,
            A0_upper=prep.a0[: prep.n + 1], A0_lower=prep.a0[prep.n + 1 :],
            zeta_T_u=prep.fit.zeta_T_upper, zeta_T_l=prep.fit.zeta_T_lower, psi=prep.psi,
            G=prep.G, b=prep.b, free_idx=prep.free_idx, alpha0=cfg.operating.alpha_deg,
            alpha_free=cfg.t8.alpha_free,
        )
        diag = NewtonDiagnostics(config=cfg)
        manifest = _make_manifest(cfg, cell_name, config_path)
        res = solve_inverse(prep.m, prob, cfg, diag=diag, run_dir=run_dir, run_manifest=manifest)

        a_final = np.concatenate([res.A_upper, res.A_lower])
        err_free = float(np.max(np.abs(a_final[prep.free_idx] - prep.a_star[prep.free_idx])))
        err_all = float(np.max(np.abs(a_final - prep.a_star)))
        log.info("RESULT: converged=%s iters=%d err_free_inf=%.3e err_all_inf=%.3e order=%s",
                  res.converged, res.iterations, err_free, err_all, res.convergence_order)

        # --- release-and-verify --------------------------------------------------------
        release_transition()
        m_ver = make_mfoil(coords=coords_from_A(
            res.A_upper, res.A_lower, prep.fit.zeta_T_upper, prep.fit.zeta_T_lower, prep.psi))
        m_ver.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
        m_ver.solve()
        dcl = abs(m_ver.post.cl - prep.nat_cl)
        dcd = abs(m_ver.post.cd - prep.nat_cd)
        # numpy bool/float comparisons chain through Python's `and` untouched
        # (short-circuit returns the operand, not a coerced type); wrap the
        # whole thing so json.dump (Python bool only) never sees np.bool_.
        verify_ok = bool(bool(m_ver.glob.conv) and dcl < 1e-3 and dcd < 2e-4)
        release_verify = {
            "cl": float(m_ver.post.cl), "cl_target": prep.nat_cl, "dcl": float(dcl),
            "cd": float(m_ver.post.cd), "cd_target": prep.nat_cd, "dcd": float(dcd),
            "converged": bool(m_ver.glob.conv), "ok": verify_ok,
        }
        log.info("release-and-verify: dcl=%.2e dcd=%.2e conv=%s ok=%s",
                  dcl, dcd, m_ver.glob.conv, verify_ok)

    return CellResult(
        cell_name=cell_name,
        manifest=manifest,
        converged=bool(res.converged),
        iterations=res.iterations,
        err_free_inf=err_free,
        err_all_inf=err_all,
        residual_history=[float(r) for r in res.residual_norms],
        convergence_order=res.convergence_order,
        n_residual_evaluations=counters.n_residual_evaluations,
        n_flow_solves_equivalent=counters.n_flow_solves_equivalent,
        release_verify=release_verify,
        realisability=prep.realisability,
        model_gap=prep.model_gap,
        submap_cond=prep.submap_cond,
        wall_time_s=time.perf_counter() - t0,
        notes=prep.notes,
    )
