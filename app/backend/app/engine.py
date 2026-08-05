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

import json
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.linalg import qr as _qr

from cins.benchmarks.instrumentation import EvalCounters, instrument_evaluations
from cins.benchmarks.pipeline import prepare_cell
from cins.config import CinsConfig, load_config
from cins.cst.basis import surface as cst_surface
from cins.cst.constraints import area_row, le_radius_row, shared_le_radius_row, te_wedge_row
from cins.cst.fit import fit_cst
from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.cst.io import UIUC_DIR, AirfoilParseError, load_airfoil_dat, uiuc_dat_path
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.mfoil_adapter import (
    make_mfoil,
    mfoil_module,
    release_transition,
    set_forced_transition,
)
from cins.solver.newton import InverseProblem, assert_square, solve_inverse
from cins.solver.presolve import (
    InviscidCpResult,
    build_sensitivity_matrix,
    interpolate_cp_to_stations,
    solve_inviscid_cp,
)
from cins.solver.presolve import presolve as engine_presolve

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
# derived engineering quantities (shared by /api/fit, /api/geometry/from-cst,
# and the /api/airfoils cache scan)
# --------------------------------------------------------------------------- #


def derived_geometry_quantities(
    A_upper: np.ndarray,
    A_lower: np.ndarray,
    zeta_T_u: float,
    zeta_T_l: float,
    N1: float = 0.5,
    N2: float = 1.0,
) -> dict[str, float]:
    """Named engineering quantities computed directly from CST coefficients —
    closed form, no quadrature (dossier §3.2-3.4): LE radius (R_LE = A_u0^2/2,
    constraints.le_radius_row's own identity, chord=1), TE wedge half-angles
    (inverse of constraints.te_wedge_row's exact TE-slope identity, N2=1),
    thickness/camber envelope located on a fine uniform psi grid (uniform, not
    cosine, so the argmax is not biased toward the LE/TE clustering), and
    inscribed area (constraints.area_row's Beta-function row)."""
    A_upper = np.asarray(A_upper, dtype=float)
    A_lower = np.asarray(A_lower, dtype=float)
    n_u, n_l = A_upper.size - 1, A_lower.size - 1

    psi_fine = np.linspace(0.0, 1.0, 401)
    z_u = cst_surface(psi_fine, A_upper, zeta_T_u, N1, N2)
    z_l = cst_surface(psi_fine, A_lower, zeta_T_l, N1, N2)
    thickness = z_u - z_l
    camber = 0.5 * (z_u + z_l)
    i_t = int(np.argmax(thickness))
    i_c = int(np.argmax(np.abs(camber)))

    le_radius = 0.5 * float(A_upper[0]) ** 2
    # inverse of te_wedge_row's identity A_n = zeta_T +/- tan(beta)
    tan_beta_u = float(A_upper[-1] - zeta_T_u)
    tan_beta_l = float(zeta_T_l - A_lower[-1])

    g_area, te_coeff = area_row(n_u, n_l, N1, N2)
    A_stack = np.concatenate([A_upper, A_lower])
    area = float(g_area @ A_stack + te_coeff @ np.array([zeta_T_u, zeta_T_l]))

    return {
        "le_radius": le_radius,
        "te_wedge_upper_deg": float(np.degrees(np.arctan(tan_beta_u))),
        "te_wedge_lower_deg": float(np.degrees(np.arctan(tan_beta_l))),
        "te_gap": float(zeta_T_u - zeta_T_l),
        "max_thickness": float(thickness[i_t]),
        "max_thickness_x": float(psi_fine[i_t]),
        "max_camber": float(camber[i_c]),
        "max_camber_x": float(psi_fine[i_c]),
        "area": area,
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
    derived = derived_geometry_quantities(
        fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, fit.N1, fit.N2
    )
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
        "derived": derived,
    }


# --------------------------------------------------------------------------- #
# /api/airfoils, /api/airfoils/{id}/geometry
# --------------------------------------------------------------------------- #

_AIRFOIL_CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "airfoils.json"
_AIRFOIL_CACHE: dict[str, Any] | None = None
_AIRFOIL_CACHE_FIT_N = 6  # cheap Bernstein order for the one-time corpus scan summary

# Curated NACA generator presets (4-digit: thickness/camber read directly off
# the code per NACA's own definition, no solve needed; 5-digit design-cl
# families included without a camber figure — dossier scope is 4-digit).
_NACA_PRESETS = [
    "0006", "0009", "0010", "0012", "0015", "0018", "0021",
    "1408", "2408", "2412", "2415", "2418", "4412", "4415", "4418",
    "6409", "6412", "23012", "23015", "23018", "63012", "64012",
]


def _scan_uiuc_cache() -> dict[str, Any]:
    """One-time corpus scan (fit_cst at a cheap order) -> thickness/camber
    summary per UIUC section, cached to JSON on first call (per spec)."""
    global _AIRFOIL_CACHE
    if _AIRFOIL_CACHE is not None:
        return _AIRFOIL_CACHE
    if _AIRFOIL_CACHE_PATH.exists():
        try:
            _AIRFOIL_CACHE = json.loads(_AIRFOIL_CACHE_PATH.read_text())
            return _AIRFOIL_CACHE
        except (OSError, ValueError):
            pass  # fall through to a fresh scan

    entries: list[dict[str, Any]] = []
    for path in sorted(UIUC_DIR.glob("*.dat")):
        try:
            X = load_airfoil_dat(path)
            fit = fit_cst(X[0], X[1], _AIRFOIL_CACHE_FIT_N)
        except Exception:  # noqa: BLE001 - corpus scan, skip any bad/unusual file
            continue
        d = derived_geometry_quantities(
            fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower
        )
        entries.append(
            {
                "id": f"uiuc:{path.stem}",
                "name": path.stem,
                "source": "uiuc",
                "thickness": d["max_thickness"],
                "camber": d["max_camber"],
                "n_points": int(X.shape[1]),
            }
        )
    _AIRFOIL_CACHE = {"uiuc": entries}
    try:
        _AIRFOIL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _AIRFOIL_CACHE_PATH.write_text(json.dumps(_AIRFOIL_CACHE))
    except OSError:
        pass  # cache is a pure optimization; an unwritable dir is not fatal
    return _AIRFOIL_CACHE


def list_airfoils() -> dict[str, Any]:
    """All UIUC sections (cached scan) + a curated NACA preset list."""
    cache = _scan_uiuc_cache()
    naca_entries = []
    for code in _NACA_PRESETS:
        thickness = int(code[-2:]) / 100.0
        camber = int(code[0]) / 100.0 if len(code) == 4 else None
        naca_entries.append(
            {
                "id": f"naca:{code}",
                "name": f"NACA {code}",
                "source": "naca",
                "thickness": thickness,
                "camber": camber,
                "n_points": None,
            }
        )
    return {"uiuc": cache["uiuc"], "naca": naca_entries}


def get_airfoil_geometry(airfoil_id: str) -> dict[str, Any]:
    """Resolve ``"uiuc:<name>"`` (via ``load_airfoil_dat``) or ``"naca:<code>"``
    (via mfoil's own paneling) to a (N,2) coordinate list."""
    if airfoil_id.startswith("uiuc:"):
        name = airfoil_id[len("uiuc:") :]
        try:
            X = load_airfoil_dat(uiuc_dat_path(name))
        except AirfoilParseError as exc:
            raise EngineError(str(exc)) from exc
        return {"id": airfoil_id, "coords": X.T.tolist()}
    if airfoil_id.startswith("naca:"):
        code = airfoil_id[len("naca:") :]
        if len(code.strip()) not in (4, 5):
            raise EngineError(f"naca code must be 4 or 5 digits, got {code!r}")
        m = make_mfoil(naca=code)
        coords = np.asarray(m.geom.xpoint, dtype=float)
        return {"id": airfoil_id, "coords": coords.T.tolist()}
    raise EngineError(f"unknown airfoil id {airfoil_id!r}; expected 'uiuc:<name>' or 'naca:<code>'")


# --------------------------------------------------------------------------- #
# /api/geometry/from-cst
# --------------------------------------------------------------------------- #


def run_geometry_from_cst(req: Any) -> dict[str, Any]:
    """Live CST -> coords preview (instant, for slider morphing) + the same
    derived-quantities readout as ``/api/fit``. ``req`` is an
    ``app.schemas.GeometryFromCSTRequest``."""
    A_upper = np.asarray(req.A_upper, dtype=float)
    A_lower = np.asarray(req.A_lower, dtype=float)
    psi = cosine_spacing(req.npoint)
    coords = coords_from_A(
        A_upper, A_lower, req.zeta_T_upper, req.zeta_T_lower, psi, req.N1, req.N2
    )
    derived = derived_geometry_quantities(
        A_upper, A_lower, req.zeta_T_upper, req.zeta_T_lower, req.N1, req.N2
    )
    return {"coords": coords.T.tolist(), "derived": derived}


# --------------------------------------------------------------------------- #
# /api/flowfield
# --------------------------------------------------------------------------- #

_FLOWFIELD_MAX_CELLS = 8000  # guard: inviscid_velocity is a pure-Python O(N) loop per point


def _point_in_polygon(px: float, py: float, xs: np.ndarray, ys: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test against the airfoil's closed loop."""
    n = xs.size
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = xs[i], ys[i]
        xj, yj = xs[j], ys[j]
        if (yi > py) != (yj > py):
            x_cross = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < x_cross:
                inside = not inside
        j = i
    return inside


def run_flowfield(req: Any) -> dict[str, Any]:
    """Inviscid velocity/Cp field on a grid (vendor ``inviscid_velocity`` at
    fixed circulation), for vector/contour/streamline rendering client-side.
    ``req`` is an ``app.schemas.FlowFieldRequest``. Inviscid-only (no viscous
    wake deficit); grid size is capped (see ``_FLOWFIELD_MAX_CELLS``)."""
    if req.coords is not None:
        coords = np.array(req.coords, dtype=float).T
        if coords.shape[0] != 2:
            raise EngineError("coords must be a list of [x, y] pairs")
        m = make_mfoil(coords=coords)
    else:
        m = make_mfoil(naca=req.naca)

    m.setoper(alpha=req.alpha, Ma=req.Ma)
    mod = mfoil_module()
    mod.solve_inviscid(m)

    nx, ny = int(req.grid.nx), int(req.grid.ny)
    if nx * ny > _FLOWFIELD_MAX_CELLS:
        raise EngineError(
            f"grid too large: {nx}x{ny}={nx * ny} cells > {_FLOWFIELD_MAX_CELLS} cap"
        )
    xs = np.linspace(req.grid.x_min, req.grid.x_max, nx)
    ys = np.linspace(req.grid.y_min, req.grid.y_max, ny)

    X = np.asarray(m.foil.x, dtype=float)
    gam = np.asarray(m.isol.gam, dtype=float)
    Vinf = float(m.param.Vinf)
    alpha = float(m.oper.alpha)
    poly_x, poly_y = X[0], X[1]

    u = [[None] * nx for _ in range(ny)]
    v = [[None] * nx for _ in range(ny)]
    speed = [[None] * nx for _ in range(ny)]
    cp = [[None] * nx for _ in range(ny)]
    for j, yy in enumerate(ys):
        for i, xx in enumerate(xs):
            if _point_in_polygon(float(xx), float(yy), poly_x, poly_y):
                continue
            vel = mod.inviscid_velocity(X, gam, Vinf, alpha, np.array([xx, yy]), False)
            uu, vv = float(vel[0]), float(vel[1])
            spd = float(np.hypot(uu, vv))
            u[j][i] = uu
            v[j][i] = vv
            speed[j][i] = spd
            cp[j][i] = 1.0 - (spd / Vinf) ** 2

    return {
        "x": xs.tolist(),
        "y": ys.tolist(),
        "u": u,
        "v": v,
        "speed": speed,
        "cp": cp,
        "airfoil": X.T.tolist(),
        "alpha": alpha,
        "Vinf": Vinf,
        "nx": nx,
        "ny": ny,
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
            "presolve_gate": None,
        }


# --------------------------------------------------------------------------- #
# /api/inverse/raw — user-defined target Cp (product requirement: target
# editor / CSV import / coordinate import), reusing the same job store as
# /api/inverse (app/jobs.py, same GET /api/inverse/{job_id} poll route).
# --------------------------------------------------------------------------- #


def _baseline_from_spec(baseline: Any, n: int) -> tuple[np.ndarray, np.ndarray, float, float]:
    """``app.schemas.BaselineSpec`` -> (A_upper, A_lower, zeta_T_u, zeta_T_l)."""
    if baseline.naca is not None:
        m_ref = make_mfoil(naca=baseline.naca)
        X = m_ref.geom.xpoint
        fit = fit_cst(X[0], X[1], n)
        return fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower
    a_u = np.asarray(baseline.A_upper, dtype=float)
    a_l = np.asarray(baseline.A_lower, dtype=float)
    zt_u = baseline.zeta_T_upper if baseline.zeta_T_upper is not None else 0.0
    zt_l = baseline.zeta_T_lower if baseline.zeta_T_lower is not None else 0.0
    return a_u, a_l, zt_u, zt_l


def build_inverse_raw_config(req: Any, n_upper: int, n_lower: int) -> CinsConfig:
    """Overlay an ``app.schemas.RawTargetInverseRequest`` onto
    ``configs/default.yaml``. Raw-target mode deliberately keeps the geometry
    simple (``le_treatment: none``, natural transition) rather than the
    dossier's forced-trip T7 self-consistency setup — this is a user-drawn
    target, not a re-derivation of a known airfoil's own Cp, so there is no
    "natural" trip location to match against (documented in app/README.md)."""
    base = load_config().model_dump()
    overrides: dict[str, Any] = {
        "operating": {"alpha_deg": req.alpha_deg, "Re": req.Re},
        "cst": {"n_upper": n_upper, "n_lower": n_lower, "le_treatment": "none"},
        "transition": {"mode": "free"},
        "t8": {"alpha_free": req.alpha_free},
    }
    merged = _deep_merge(base, overrides)
    return CinsConfig.model_validate(merged)


def run_presolve_gate_raw(req: Any) -> dict[str, Any]:
    """Just the T4 gate (no Newton solve) — used both standalone (so the UI
    can show the verdict before the user commits to a full inverse run) and
    as the first step of ``run_inverse_raw`` itself."""
    a_u0, a_l0, zeta_t_u, zeta_t_l = _baseline_from_spec(req.baseline, req.n)
    n_u, n_l = a_u0.size - 1, a_l0.size - 1
    cfg = build_inverse_raw_config(req, n_u, n_l)
    psi = cosine_spacing(_PSI_NPOINT)

    target_x = np.asarray(req.target.x, dtype=float)
    target_cp = np.asarray(req.target.to_cp(), dtype=float)
    target_res = InviscidCpResult(x=target_x, cp=target_cp, le_idx=int(np.argmin(target_x)))

    constraint_rows = _build_constraint_rows(req.constraints, n_u, n_l)
    resolved_rows: list[tuple[np.ndarray, float]] = []
    has_le_row = any(c.type in ("shared_le_radius", "le_radius") for c in req.constraints)
    for row in constraint_rows:
        if len(row) == 3:
            g, target_area, te_coeff = row
            b = float(target_area - te_coeff @ np.array([zeta_t_u, zeta_t_l]))
            resolved_rows.append((g, b))
        else:
            resolved_rows.append(row)  # type: ignore[arg-type]

    a0 = np.concatenate([a_u0, a_l0])
    ps = None
    for _ in range(2):  # two presolve passes, mirroring prepare_cell's own init="presolve" loop
        base_res = solve_inviscid_cp(
            a0[: n_u + 1], a0[n_u + 1 :], zeta_t_u, zeta_t_l, psi, cfg
        )
        cp_t_at_a0 = interpolate_cp_to_stations(target_res, base_res)
        rows = resolved_rows
        if not has_le_row:
            # Target-consistent closure (memory note: b = g.A*, not an idealized
            # value) using the best available proxy for A* — the presolved a0
            # itself, refreshed every pass.
            g_row, _ = shared_le_radius_row(n_u, n_l)
            rows = [*resolved_rows, (g_row, float(g_row @ a0))]
        ps = engine_presolve(
            cp_t_at_a0, a0[: n_u + 1], a0[n_u + 1 :], zeta_t_u, zeta_t_l, psi, rows, cfg
        )
        a0 = np.asarray(ps.A, dtype=float)

    assert ps is not None
    return {
        "cfg": cfg,
        "psi": psi,
        "target_res": target_res,
        "a0": a0,
        "zeta_t_u": zeta_t_u,
        "zeta_t_l": zeta_t_l,
        "n_u": n_u,
        "n_l": n_l,
        "ps": ps,
        "gate": {
            "realisability": ps.realisability,
            "realisable": ps.realisable,
            "kkt_cond": ps.kkt_cond,
            "threshold": cfg.presolve.realisability_threshold,
            "A_upper_init": a0[: n_u + 1].tolist(),
            "A_lower_init": a0[n_u + 1 :].tolist(),
        },
    }


def run_inverse_raw(req: Any, cell_name: str = "api-inverse-raw") -> dict[str, Any]:
    """User-defined-target monolithic CST-Newton inverse solve. Runs the T4
    presolve gate first (``run_presolve_gate_raw``) and ALWAYS returns its
    verdict via ``presolve_gate`` — even on an early failure — so the UI can
    surface the realisability warning regardless of what happens next.
    ``req`` is an ``app.schemas.RawTargetInverseRequest``."""
    t0 = time.perf_counter()
    gate_ctx = run_presolve_gate_raw(req)
    cfg = gate_ctx["cfg"]
    psi = gate_ctx["psi"]
    target_res = gate_ctx["target_res"]
    a0 = gate_ctx["a0"]
    zeta_t_u, zeta_t_l = gate_ctx["zeta_t_u"], gate_ctx["zeta_t_l"]
    n_u, n_l = gate_ctx["n_u"], gate_ctx["n_l"]
    gate = gate_ctx["gate"]

    def _early(notes: list[str], dof_check_error: str | None = None) -> dict[str, Any]:
        return {
            "converged": False, "iterations": 0, "alpha": None,
            "A_upper": None, "A_lower": None, "coords": None,
            "residual_history": [], "convergence_order": None, "release_verify": None,
            "realisability": gate["realisability"], "model_gap": None, "submap_cond": None,
            "notes": notes, "dof_check_error": dof_check_error,
            "wall_time_s": time.perf_counter() - t0, "diagnostics": [],
            "manifest": {"cell_name": cell_name, "config_hash": cfg.config_hash()},
            "presolve_gate": gate,
        }

    n_a = n_u + n_l + 2
    free_idx = np.arange(n_a)
    g_row, _ = shared_le_radius_row(n_u, n_l)
    has_le_row = any(c.type in ("shared_le_radius", "le_radius") for c in req.constraints)
    if has_le_row:
        raw_rows = _build_constraint_rows(req.constraints, n_u, n_l)
        G_rows: list[np.ndarray] = []
        b_rows: list[float] = []
        for row in raw_rows:
            if len(row) == 3:
                g, target_area, te_coeff = row
                G_rows.append(g)
                b_rows.append(float(target_area - te_coeff @ np.array([zeta_t_u, zeta_t_l])))
            else:
                g, b = row
                G_rows.append(g)
                b_rows.append(b)
        G = np.stack(G_rows)
        b = np.array(b_rows)
    else:
        G = g_row.reshape(1, -1)
        b = np.array([float(g_row @ a0)])

    n_alpha = 1 if req.alpha_free else 0
    n_targets_required = len(free_idx) + n_alpha - G.shape[0]

    # Rebuild the sensitivity matrix at the FINAL presolved a0 (not the
    # pre-update pass ``ps.sensitivity`` used internally by
    # ``run_presolve_gate_raw``'s loop) so station selection and the
    # initial-guess geometry solved below are for the identical baseline —
    # avoids the node-index drift ``prepare_cell`` guards against.
    sens = build_sensitivity_matrix(a0[: n_u + 1], a0[n_u + 1 :], zeta_t_u, zeta_t_l, psi, cfg)
    n_pick = n_targets_required + req.n_stations_offset
    if n_pick <= 0 or n_pick > sens.x_stations.size:
        return _early([f"invalid station count requested: n_pick={n_pick}"])
    m_cand = sens.M[:, free_idx]
    _, _, piv = _qr(m_cand.T, pivoting=True)
    stations = np.sort(piv[:n_pick])

    try:
        assert_square(len(free_idx), len(stations), G.shape[0], alpha_free=req.alpha_free)
    except ValueError as exc:
        return _early(["DOF check failed"], dof_check_error=str(exc))

    cp_t_at_a0 = interpolate_cp_to_stations(target_res, sens.baseline)
    cp_target = cp_t_at_a0[stations]

    with MFOIL_LOCK:
        coords0 = coords_from_A(
            a0[: n_u + 1], a0[n_u + 1 :], zeta_t_u, zeta_t_l, psi, cfg.cst.N1, cfg.cst.N2
        )
        m = make_mfoil(coords=coords0, npanel=cfg.paneling.npanel)
        m.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
        m.solve()
        if not m.glob.conv:
            return _early(["flow solve at the presolved initial guess failed to converge"])

        prob = InverseProblem(
            cp_target=cp_target,
            station_idx=stations,
            A0_upper=a0[: n_u + 1],
            A0_lower=a0[n_u + 1 :],
            zeta_T_u=zeta_t_u,
            zeta_T_l=zeta_t_l,
            psi=psi,
            G=G,
            b=b,
            free_idx=free_idx,
            alpha0=cfg.operating.alpha_deg,
            alpha_free=req.alpha_free,
        )
        diag = NewtonDiagnostics(config=cfg)
        res = solve_inverse(m, prob, cfg, diag=diag)

        coords = coords_from_A(res.A_upper, res.A_lower, zeta_t_u, zeta_t_l, psi)

        release_transition()
        m_ver = make_mfoil(coords=coords)
        m_ver.setoper(alpha=res.alpha, Re=cfg.operating.Re)
        m_ver.solve()
        release_verify = {
            "cl": float(m_ver.post.cl), "cd": float(m_ver.post.cd),
            "converged": bool(m_ver.glob.conv),
            "note": (
                "raw target has no natural cl/cd to compare against; "
                "reports the achieved state only"
            ),
        }

        diag_summary = [
            {
                "it": r.it, "R_norm": r.R_norm, "T_norm": r.T_norm, "G_norm": r.G_norm,
                "rank_J": r.rank_J, "cond_J": r.cond_J, "omega": r.omega, "dA_norm": r.dA_norm,
            }
            for r in diag._iterations  # noqa: SLF001 - in-process summary, not a public API
        ]

    return {
        "converged": bool(res.converged),
        "iterations": res.iterations,
        "alpha": res.alpha,
        "A_upper": res.A_upper.tolist(),
        "A_lower": res.A_lower.tolist(),
        "coords": coords.T.tolist(),
        "residual_history": [float(x) for x in res.residual_norms],
        "convergence_order": res.convergence_order,
        "release_verify": release_verify,
        "realisability": gate["realisability"],
        "model_gap": None,
        "submap_cond": (
            float(np.linalg.cond(sens.M[stations][:, free_idx])) if stations.size else None
        ),
        "notes": [],
        "dof_check_error": None,
        "wall_time_s": time.perf_counter() - t0,
        "diagnostics": diag_summary,
        "manifest": {
            "cell_name": cell_name,
            "config_hash": cfg.config_hash(),
            "cst": {"n_upper": n_u, "n_lower": n_l, "le_treatment": "none"},
            "transition_mode": "free",
        },
        "presolve_gate": gate,
    }
