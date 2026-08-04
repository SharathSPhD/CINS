"""Thin wrapper over ``cins`` (the deterministic engine core) — the "FastAPI
backend" layer of the kundali architecture (docs/PRD.md §3.2). No physics or
numerics lives here: every array in/out of this module passes straight
through to ``cins.cst`` / ``cins.solver`` / ``cins.benchmarks.pipeline``
functions. This module only adapts shapes (JSON-friendly lists <-> numpy) and
orchestrates the same call sequences ``cins.benchmarks.pipeline.run_pipeline``
uses (``prepare_cell`` -> ``InverseProblem`` -> ``solve_inverse``), reusing
those "pipeline pieces" directly rather than reimplementing the monolithic
Newton solve.

Concurrency guard (ADR-0003 consequence): mfoil's forced-transition shim
(``set_forced_transition``/``release_transition``) reassigns MODULE-LEVEL
vendor functions, so it is process-global — any two solves running forced
transition concurrently in this process would corrupt each other's state.
``MFOIL_LOCK`` below is held around every code path that may install the
shim (``/api/inverse``'s pipeline, and ``/api/analyze`` when
``transition.mode == "forced"``); other endpoints (``fit`` — pure numpy,
touches no mfoil state; plain ``analyze``/``presolve`` — independent mfoil
instances, natural transition only) do not need it.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from cins.benchmarks.instrumentation import EvalCounters, instrument_evaluations
from cins.benchmarks.pipeline import prepare_cell
from cins.config import CinsConfig, load_config
from cins.cst.constraints import area_row, le_radius_row, shared_le_radius_row, te_wedge_row
from cins.cst.fit import fit_cst
from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.mfoil_adapter import (
    make_mfoil,
    mfoil_module,
    release_transition,
    set_forced_transition,
)
from cins.solver.newton import InverseProblem, solve_inverse
from cins.solver.presolve import (
    InviscidCpResult,
    build_sensitivity_matrix,
    interpolate_cp_to_stations,
    presolve as engine_presolve,
)

# Process-global: guards mfoil's process-global forced-transition shim
# (ADR-0003) AND enforces "one inverse at a time" (docs/PRD.md phase-1 spec).
MFOIL_LOCK = threading.Lock()

_PSI_NPOINT = 160  # matches cins.benchmarks.pipeline._PSI_NPOINT


class EngineError(ValueError):
    """Raised for engine-level failures the API layer turns into 4xx JSON."""


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #


def _split_ascending(
    x: np.ndarray, val: np.ndarray, le_idx: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split a full-loop (x, val) pair at ``le_idx`` into two x-ascending
    surfaces, mirroring ``cins.solver.presolve``'s private ``_split_ascending``
    (duplicated here — a few lines — rather than importing a private symbol
    across the app/engine boundary)."""

    def _asc(xx: np.ndarray, vv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if xx.size >= 2 and xx[0] > xx[-1]:
            return xx[::-1], vv[::-1]
        return xx, vv

    x_lo, v_lo = _asc(x[: le_idx + 1], val[: le_idx + 1])
    x_up, v_up = _asc(x[le_idx:], val[le_idx:])
    return x_lo, v_lo, x_up, v_up


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Same semantics as ``cins.config._deep_merge`` (private there); local
    copy so the app layer doesn't reach into a package-private helper."""
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# /api/analyze
# --------------------------------------------------------------------------- #


def run_analyze(req: Any) -> dict[str, Any]:
    """Direct mfoil solve on the given geometry. ``req`` is an
    ``app.schemas.AnalyzeRequest``."""
    if req.coords is not None:
        coords = np.array(req.coords, dtype=float).T  # (N,2) -> (2,N)
        if coords.shape[0] != 2:
            raise EngineError("coords must be a list of [x, y] pairs")
        m = make_mfoil(coords=coords)
    else:
        m = make_mfoil(naca=req.naca)

    m.setoper(alpha=req.alpha, Re=req.Re, Ma=req.Ma)
    mod = mfoil_module()

    forced = req.transition is not None and req.transition.mode == "forced"
    if forced and req.Re is None:
        raise EngineError("forced transition requires a viscous solve (Re must be given)")

    if forced:
        with MFOIL_LOCK:
            m.solve()  # natural viscous solve first, to identify vsol.Is
            if m.glob.conv:
                set_forced_transition(m, req.transition.xtr_upper, req.transition.xtr_lower)
                try:
                    mod.solve_coupled(m)
                    mod.calc_force(m)
                finally:
                    release_transition()
    else:
        m.solve()

    converged = bool(m.glob.conv)
    x = np.asarray(m.foil.x[0], dtype=float)
    cp = np.asarray(m.post.cp, dtype=float)
    le_idx = int(np.argmin(x))
    x_lo, cp_lo, x_up, cp_up = _split_ascending(x, cp, le_idx)
    geom = np.asarray(m.geom.xpoint, dtype=float)  # (2, N)

    return {
        "converged": converged,
        "cl": float(m.post.cl),
        "cd": float(m.post.cd),
        "cm": float(m.post.cm),
        "alpha": float(m.oper.alpha),
        "Re": req.Re,
        "Ma": req.Ma,
        "x": x.tolist(),
        "cp": cp.tolist(),
        "upper": {"x": x_up.tolist(), "cp": cp_up.tolist()},
        "lower": {"x": x_lo.tolist(), "cp": cp_lo.tolist()},
        "coords": geom.T.tolist(),
    }


# --------------------------------------------------------------------------- #
# /api/fit
# --------------------------------------------------------------------------- #


def run_fit(req: Any) -> dict[str, Any]:
    """CST fit to supplied coordinates. ``req`` is an ``app.schemas.FitRequest``."""
    coords = np.array(req.coords, dtype=float)
    if coords.shape[1] != 2:
        raise EngineError("coords must be a list of [x, y] pairs")
    x, y = coords[:, 0], coords[:, 1]
    fit = fit_cst(x, y, req.n, req.N1, req.N2, req.te_gap)
    return {
        "A_upper": fit.A_upper.tolist(),
        "A_lower": fit.A_lower.tolist(),
        "zeta_T_upper": fit.zeta_T_upper,
        "zeta_T_lower": fit.zeta_T_lower,
        "n": fit.n,
        "N1": fit.N1,
        "N2": fit.N2,
        "rms": fit.rms,
        "gram_condition": fit.gram_condition,
    }


# --------------------------------------------------------------------------- #
# /api/presolve
# --------------------------------------------------------------------------- #


def _build_constraint_rows(
    constraints: list[Any], n_upper: int, n_lower: int
) -> list[tuple[np.ndarray, float]]:
    rows: list[tuple[np.ndarray, float]] = []
    for c in constraints:
        if c.type == "shared_le_radius":
            rows.append(shared_le_radius_row(n_upper, n_lower))
        elif c.type == "le_radius":
            if c.R_LE is None:
                raise EngineError("constraint `le_radius` requires `R_LE`")
            rows.append(le_radius_row(n_upper, n_lower, c.R_LE))
        elif c.type == "te_wedge":
            if c.beta is None or c.dz_TE is None:
                raise EngineError("constraint `te_wedge` requires `beta` and `dz_TE`")
            rows.append(te_wedge_row(n_upper, n_lower, c.beta, c.dz_TE, c.side))
        elif c.type == "area":
            if c.target_area is None:
                raise EngineError("constraint `area` requires `target_area`")
            g, te_coeff = area_row(n_upper, n_lower)
            # area = g@A + te_coeff@[zeta_T_u, zeta_T_l]; solved per-baseline
            # below once zeta_T is known, so stash te_coeff on the row tuple's
            # b via a closure is not possible here (rows are plain (g,b) —
            # resolved by the caller, which has zeta_T in scope).
            rows.append((g, c.target_area, te_coeff))  # type: ignore[arg-type]
        else:  # pragma: no cover - pydantic Literal already restricts this
            raise EngineError(f"unknown constraint type {c.type!r}")
    return rows


def run_presolve(req: Any, cfg: CinsConfig | None = None) -> dict[str, Any]:
    """Linear pre-solve + realisability metric (T4, dossier §7.5).
    ``req`` is an ``app.schemas.PresolveRequest``."""
    cfg = cfg or load_config()
    psi = cosine_spacing(_PSI_NPOINT)

    if req.baseline.naca is not None:
        m_ref = make_mfoil(naca=req.baseline.naca)
        X = m_ref.geom.xpoint
        fit = fit_cst(X[0], X[1], req.n)
        a_u0, a_l0 = fit.A_upper, fit.A_lower
        zeta_t_u, zeta_t_l = fit.zeta_T_upper, fit.zeta_T_lower
    else:
        a_u0 = np.asarray(req.baseline.A_upper, dtype=float)
        a_l0 = np.asarray(req.baseline.A_lower, dtype=float)
        zeta_t_u = req.baseline.zeta_T_upper if req.baseline.zeta_T_upper is not None else 0.0
        zeta_t_l = req.baseline.zeta_T_lower if req.baseline.zeta_T_lower is not None else 0.0

    n_u = a_u0.size
    n_l = a_l0.size

    sens = build_sensitivity_matrix(a_u0, a_l0, zeta_t_u, zeta_t_l, psi, cfg)

    target_x = np.asarray(req.target.x, dtype=float)
    target_cp = np.asarray(req.target.cp, dtype=float)
    target_res = InviscidCpResult(x=target_x, cp=target_cp, le_idx=int(np.argmin(target_x)))
    cp_target_at_baseline = interpolate_cp_to_stations(target_res, sens.baseline)

    raw_rows = _build_constraint_rows(req.constraints, n_u - 1, n_l - 1)
    constraint_rows: list[tuple[np.ndarray, float]] = []
    for row in raw_rows:
        if len(row) == 3:  # area row: resolve b against this baseline's zeta_T
            g, target_area, te_coeff = row
            b = float(target_area - te_coeff @ np.array([zeta_t_u, zeta_t_l]))
            constraint_rows.append((g, b))
        else:
            constraint_rows.append(row)  # type: ignore[arg-type]

    result = engine_presolve(
        cp_target_at_baseline, a_u0, a_l0, zeta_t_u, zeta_t_l, psi, constraint_rows, cfg
    )

    return {
        "A_upper_init": result.A[:n_u].tolist(),
        "A_lower_init": result.A[n_u:].tolist(),
        "delta_A": result.delta_A.tolist(),
        "realisability": result.realisability,
        "realisability_label": "inviscid-consistent (ADR-0004)",
        "realisable": result.realisable,
        "kkt_cond": result.kkt_cond,
        "target_kind": req.target.kind,
        # model_gap (ADR-0004 metric 2) needs a matched viscous baseline solve,
        # which only naturally exists inside the /api/inverse pipeline's own
        # T4 presolve step (see run_inverse below) — not computed standalone
        # here. Documented in app/README.md.
        "model_gap": None,
        "n_stations": int(cp_target_at_baseline.size),
    }


# --------------------------------------------------------------------------- #
# /api/inverse
# --------------------------------------------------------------------------- #


def build_inverse_config(req: Any) -> CinsConfig:
    """Overlay an ``app.schemas.InverseRequest`` onto ``configs/default.yaml``."""
    base = load_config().model_dump()
    overrides: dict[str, Any] = {
        "operating": {"alpha_deg": req.alpha_deg, "Re": req.Re, "Ma": req.Ma},
        "t8": {
            "airfoil": req.airfoil,
            "station_selection": req.station_selection,
            "init": req.init,
            "alpha_free": req.alpha_free,
            "dof_offset": req.dof_offset,
        },
    }
    cst_overrides: dict[str, Any] = {}
    if req.le_treatment is not None:
        cst_overrides["le_treatment"] = req.le_treatment
    if req.n_upper is not None:
        cst_overrides["n_upper"] = req.n_upper
    if req.n_lower is not None:
        cst_overrides["n_lower"] = req.n_lower
    if cst_overrides:
        overrides["cst"] = cst_overrides
    if req.transition_mode is not None:
        overrides["transition"] = {"mode": req.transition_mode}

    merged = _deep_merge(base, overrides)
    return CinsConfig.model_validate(merged)


def run_inverse(cfg: CinsConfig, cell_name: str = "api-inverse") -> dict[str, Any]:
    """Run the monolithic CST-Newton inverse solve, composed from the same
    "pipeline pieces" ``cins.benchmarks.pipeline.run_pipeline`` uses
    (``prepare_cell`` -> ``InverseProblem`` -> ``solve_inverse``), but also
    surfaces the final ``A``/coords the API needs (``run_pipeline`` itself
    only returns a ``CellResult`` with recovery-error diagnostics, not the
    final geometry). Holds ``MFOIL_LOCK`` for the whole solve (ADR-0003 +
    "one inverse at a time")."""
    t0 = time.perf_counter()
    counters = EvalCounters()

    with MFOIL_LOCK:
        with instrument_evaluations(counters):
            prep = prepare_cell(cfg, counters, cell_name=cell_name, t0=t0)
            if prep.early_failure is not None:
                ef = prep.early_failure
                return {
                    "converged": False,
                    "iterations": 0,
                    "alpha": None,
                    "A_upper": None,
                    "A_lower": None,
                    "coords": None,
                    "residual_history": [],
                    "convergence_order": None,
                    "release_verify": None,
                    "realisability": None,
                    "model_gap": None,
                    "submap_cond": None,
                    "notes": ef.notes,
                    "dof_check_error": ef.dof_check_error,
                    "wall_time_s": time.perf_counter() - t0,
                    "diagnostics": [],
                    "manifest": ef.manifest,
                }

            prob = InverseProblem(
                cp_target=prep.cp_target,
                station_idx=prep.stations,
                A0_upper=prep.a0[: prep.n + 1],
                A0_lower=prep.a0[prep.n + 1 :],
                zeta_T_u=prep.fit.zeta_T_upper,
                zeta_T_l=prep.fit.zeta_T_lower,
                psi=prep.psi,
                G=prep.G,
                b=prep.b,
                free_idx=prep.free_idx,
                alpha0=cfg.operating.alpha_deg,
                alpha_free=cfg.t8.alpha_free,
            )
            diag = NewtonDiagnostics(config=cfg)
            res = solve_inverse(prep.m, prob, cfg, diag=diag)

            coords = coords_from_A(
                res.A_upper, res.A_lower, prep.fit.zeta_T_upper, prep.fit.zeta_T_lower, prep.psi
            )

            # release-and-verify (same protocol as run_pipeline)
            release_transition()
            m_ver = make_mfoil(coords=coords)
            m_ver.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
            m_ver.solve()
            dcl = abs(m_ver.post.cl - prep.nat_cl)
            dcd = abs(m_ver.post.cd - prep.nat_cd)
            verify_ok = bool(bool(m_ver.glob.conv) and dcl < 1e-3 and dcd < 2e-4)
            release_verify = {
                "cl": float(m_ver.post.cl), "cl_target": prep.nat_cl, "dcl": float(dcl),
                "cd": float(m_ver.post.cd), "cd_target": prep.nat_cd, "dcd": float(dcd),
                "converged": bool(m_ver.glob.conv), "ok": verify_ok,
            }

            diag_summary = [
                {
                    "it": r.it,
                    "R_norm": r.R_norm,
                    "T_norm": r.T_norm,
                    "G_norm": r.G_norm,
                    "rank_J": r.rank_J,
                    "cond_J": r.cond_J,
                    "omega": r.omega,
                    "dA_norm": r.dA_norm,
                }
                for r in diag._iterations  # noqa: SLF001 - in-process summary, not a public API
            ]

        manifest = {
            "cell_name": cell_name,
            "config_hash": cfg.config_hash(),
            "t8_factors": cfg.t8.model_dump(),
            "cst": {
                "n_upper": cfg.cst.n_upper, "n_lower": cfg.cst.n_lower,
                "le_treatment": cfg.cst.le_treatment,
            },
            "transition_mode": cfg.transition.mode,
        }

        return {
            "converged": bool(res.converged),
            "iterations": res.iterations,
            "alpha": res.alpha,
            "A_upper": res.A_upper.tolist(),
            "A_lower": res.A_lower.tolist(),
            "coords": coords.T.tolist(),  # (N,2) — friendlier for JSON/plotting
            "residual_history": [float(x) for x in res.residual_norms],
            "convergence_order": res.convergence_order,
            "release_verify": release_verify,
            "realisability": prep.realisability,
            "model_gap": prep.model_gap,
            "submap_cond": prep.submap_cond,
            "notes": prep.notes,
            "dof_check_error": None,
            "wall_time_s": time.perf_counter() - t0,
            "diagnostics": diag_summary,
            "manifest": manifest,
        }
