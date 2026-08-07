"""Thin wrapper over ``cins`` (the deterministic engine core): the "FastAPI
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
vendor functions, so it is process-global: any two solves running forced
transition concurrently in this process would corrupt each other's state.
``MFOIL_LOCK`` below is held around every code path that may install the
shim (``/api/inverse``'s pipeline, and ``/api/analyze`` when
``transition.mode == "forced"``); other endpoints (``fit``: pure numpy,
touches no mfoil state; plain ``analyze``/``presolve``: independent mfoil
instances, natural transition only) do not need it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.linalg import qr as _qr

from app.flowfield import inviscid_velocity_field, points_in_polygon
from cins.benchmarks.instrumentation import EvalCounters, instrument_evaluations
from cins.benchmarks.pipeline import prepare_cell
from cins.config import REPO_ROOT, CinsConfig, load_config
from cins.cst.basis import surface as cst_surface
from cins.cst.constraints import area_row, le_radius_row, shared_le_radius_row, te_wedge_row
from cins.cst.fit import fit_cst
from cins.cst.geometry import coords_from_A, cosine_spacing
from cins.cst.io import UIUC_DIR, AirfoilParseError, load_airfoil_dat, uiuc_dat_path
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.mfoil_adapter import (
    make_mfoil,
    mfoil_module,
    refresh_post,
    release_transition,
    set_forced_transition,
)
from cins.solver.newton import (
    InverseProblem,
    assert_square,
    interpolate_cp_at_stations,
    solve_inverse,
    stations_from_indices,
)
from cins.solver.presolve import (
    InviscidCpResult,
    build_sensitivity_matrix,
    interpolate_cp_to_stations,
    solve_inviscid_cp,
)
from cins.solver.presolve import presolve as engine_presolve

logger = logging.getLogger(__name__)

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
    (duplicated here: a few lines: rather than importing a private symbol
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

# A viscous solve is deterministic in its request, so the same request always
# has the same answer and is worth keeping. The application runs on a shared
# free-tier container where that solve measures ~115 s against ~3.5 s on a
# development machine, so a repeat request is the difference between two
# minutes and nothing at all. Bounded because the container's memory is small
# and each entry carries several node-length arrays; insertion-ordered, so the
# oldest entry is the one evicted.
_ANALYZE_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_ANALYZE_CACHE_MAX = 64
_ANALYZE_CACHE_LOCK = threading.Lock()


def _analyze_cache_key(req: Any, npanel: int) -> str:
    """Content hash of everything that changes the answer. Coordinates are
    rounded before hashing so a geometry that only differs in float noise
    still hits, and included in full otherwise, since two different sections
    must never share an entry."""
    tr = req.transition
    payload = {
        "naca": req.naca,
        "coords": (
            [[round(float(a), 9), round(float(b), 9)] for a, b in req.coords]
            if req.coords is not None
            else None
        ),
        "alpha": round(float(req.alpha), 9),
        "Re": None if req.Re is None else round(float(req.Re), 6),
        "Ma": round(float(req.Ma), 9),
        "npanel": int(npanel),
        "transition": None if tr is None else [tr.mode, tr.xtr_upper, tr.xtr_lower],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def analyze_cache_stats() -> dict[str, int]:
    with _ANALYZE_CACHE_LOCK:
        return {"entries": len(_ANALYZE_CACHE), "capacity": _ANALYZE_CACHE_MAX}


def run_analyze(
    req: Any, on_progress: Callable[[dict[str, Any]], None] | None = None
) -> dict[str, Any]:
    """Direct mfoil solve on the given geometry. ``req`` is an
    ``app.schemas.AnalyzeRequest``.

    Runs at ``paneling.npanel_interactive`` rather than the study
    ``paneling.npanel``: a user is waiting on a shared container here, and the
    coarser count costs 0.09 percent in cl and 0.33 percent in cd while
    running 1.7x faster (pinned by tests/unit/test_interactive_paneling.py).
    The count used is reported back in the response so the difference is
    visible rather than silent. Callers that need the study paneling pass
    ``npanel`` explicitly."""
    cfg_paneling = load_config().paneling
    npanel = getattr(req, "npanel", None) or cfg_paneling.npanel_interactive

    def _phase(text: str) -> None:
        if on_progress is not None:
            on_progress({"phase": text})

    key = _analyze_cache_key(req, npanel)
    with _ANALYZE_CACHE_LOCK:
        hit = _ANALYZE_CACHE.get(key)
        if hit is not None:
            _ANALYZE_CACHE.move_to_end(key)
            return {**hit, "cached": True}

    if req.coords is not None:
        coords = np.array(req.coords, dtype=float).T  # (N,2) -> (2,N)
        if coords.shape[0] != 2:
            raise EngineError("coords must be a list of [x, y] pairs")
        m = make_mfoil(coords=coords, npanel=npanel)
    else:
        m = make_mfoil(naca=req.naca, npanel=npanel)

    _phase("viscous solve" if req.Re is not None else "inviscid solve")
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
                    # Both halves of m.post, not just the forces: calc_force
                    # alone leaves the boundary-layer distributions describing
                    # the natural solve above, so the response would report a
                    # tripped cl/cd beside an untripped BL (see
                    # mfoil_adapter.refresh_post).
                    refresh_post(m)
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

    # Inviscid Cp overlay (mfoil's plot_cpplus draws this dashed alongside the
    # solid viscous/inviscid Cp: m.post.cpi is computed by calc_force
    # regardless of viscous/inviscid mode, cost-free here) and the sonic Cp
    # line (m.param.cps, only meaningful for Ma>0: plot_cpplus only draws it
    # when it falls within the current Cp range).
    cpi = np.asarray(m.post.cpi, dtype=float) if hasattr(m.post, "cpi") else None
    cpi_lo = cpi_up = None
    if cpi is not None:
        _, cpi_lo, _, cpi_up = _split_ascending(x, cpi, le_idx)
    sonic_cp = None
    if req.Ma and req.Ma > 0:
        cps = getattr(getattr(m, "param", None), "cps", None)
        if cps is not None and cps > float(np.min(cp)) - 0.2:
            sonic_cp = float(cps)

    bl = None
    bl_offset = None
    n_foil = int(getattr(m.foil, "N", x.size))
    if req.Re is not None and converged and len(getattr(m.post, "th", [])) >= n_foil:
        chord = float(m.geom.chord) or 1.0
        # post.{th,ds,sa,ue,uei,cf,Ret,Hk} are Nsys-long (foil nodes THEN wake
        # nodes, per M.glob.Nsys = M.foil.N + M.wake.N): slice to the
        # foil-only prefix so these line up 1:1 with m.foil.x / x / cp above.
        theta = np.asarray(m.post.th, dtype=float)[:n_foil]
        dstar = np.asarray(m.post.ds, dtype=float)[:n_foil]
        cf = np.asarray(m.post.cf, dtype=float)[:n_foil]
        hk = np.asarray(m.post.Hk, dtype=float)[:n_foil]
        sa = np.asarray(m.post.sa, dtype=float)[:n_foil]
        ue = np.asarray(m.post.ue, dtype=float)[:n_foil]
        uei = np.asarray(m.post.uei, dtype=float)[:n_foil]
        ret = np.asarray(m.post.Ret, dtype=float)[:n_foil]

        def _surface(arr: np.ndarray) -> dict[str, list[float]]:
            lo, up = arr[: le_idx + 1], arr[le_idx:]
            lo = lo[::-1] if x[: le_idx + 1][0] > x[: le_idx + 1][-1] else lo
            up = up[::-1] if x[le_idx:][0] > x[le_idx:][-1] else up
            return {"lower": lo.tolist(), "upper": up.tolist()}

        xt = m.vsol.Xt if hasattr(m.vsol, "Xt") else None
        bl = {
            "x": {"lower": x_lo.tolist(), "upper": x_up.tolist()},
            "theta": _surface(theta),
            "delta_star": _surface(dstar),
            "cf": _surface(cf),
            "Hk": _surface(hk),
            "amplification": _surface(sa),
            "ue": _surface(ue),
            "uei": _surface(uei),
            "Re_theta": _surface(ret),
            "transition_x": (
                {"upper": float(xt[1, 1]) / chord, "lower": float(xt[0, 1]) / chord}
                if xt is not None
                else None
            ),
        }

        # Displacement-thickness offset drawn along outward surface normals
        # (mfoil's mplot_boundary_layer: xzd = xz + n*ds, n = normalize(-ty,tx)
        # from the panel tangents m.foil.t): the airfoil "puffed out" by
        # delta* the way mfoil's own results plot shows it, foil nodes only
        # (no wake reflection: that's a plotting artifact specific to mfoil's
        # own axes, not meaningful for a standalone airfoil-shape panel).
        t = np.asarray(m.foil.t, dtype=float)[:, :n_foil] if hasattr(m.foil, "t") else None
        if t is not None:
            n_vec = np.vstack([-t[1], t[0]])
            norms = np.linalg.norm(n_vec, axis=0)
            norms[norms == 0] = 1.0
            n_vec = n_vec / norms
            xz = np.asarray(m.foil.x, dtype=float)[:, :n_foil]
            ds_full = np.asarray(m.post.ds, dtype=float)[:n_foil]
            xzd = xz + n_vec * ds_full
            xd, yd = xzd[0], xzd[1]

            def _surface_xy(xarr: np.ndarray, yarr: np.ndarray) -> list[list[float]]:
                xs, ys = xarr[: le_idx + 1], yarr[: le_idx + 1]
                if xs[0] > xs[-1]:
                    xs, ys = xs[::-1], ys[::-1]
                return np.stack([xs, ys], axis=1).tolist()

            lo_pts = _surface_xy(xd[: le_idx + 1], yd[: le_idx + 1])
            xs_up, ys_up = xd[le_idx:], yd[le_idx:]
            if xs_up[0] > xs_up[-1]:
                xs_up, ys_up = xs_up[::-1], ys_up[::-1]
            up_pts = np.stack([xs_up, ys_up], axis=1).tolist()
            bl_offset = {"lower": lo_pts, "upper": up_pts}

    result = {
        "converged": converged,
        "cl": float(m.post.cl),
        "cd": float(m.post.cd),
        "cm": float(m.post.cm),
        "cdf": float(m.post.cdf) if req.Re is not None and hasattr(m.post, "cdf") else None,
        "cdp": float(m.post.cdp) if req.Re is not None and hasattr(m.post, "cdp") else None,
        "alpha": float(m.oper.alpha),
        "Re": req.Re,
        "Ma": req.Ma,
        "x": x.tolist(),
        "cp": cp.tolist(),
        "upper": {"x": x_up.tolist(), "cp": cp_up.tolist()},
        "lower": {"x": x_lo.tolist(), "cp": cp_lo.tolist()},
        "upper_cpi": {"x": x_up.tolist(), "cp": cpi_up.tolist()} if cpi_up is not None else None,
        "lower_cpi": {"x": x_lo.tolist(), "cp": cpi_lo.tolist()} if cpi_lo is not None else None,
        "sonic_cp": sonic_cp,
        "coords": geom.T.tolist(),
        "bl": bl,
        "bl_offset": bl_offset,
        "npanel": int(npanel),
        "cached": False,
    }

    with _ANALYZE_CACHE_LOCK:
        _ANALYZE_CACHE[key] = result
        _ANALYZE_CACHE.move_to_end(key)
        while len(_ANALYZE_CACHE) > _ANALYZE_CACHE_MAX:
            _ANALYZE_CACHE.popitem(last=False)
    return result


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
    """Named engineering quantities computed directly from CST coefficients ,
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
# families included without a camber figure: dossier scope is 4-digit).
_NACA_PRESETS = [
    "0006", "0009", "0010", "0012", "0015", "0018", "0021",
    "1408", "2408", "2412", "2415", "2418", "4412", "4415", "4418",
    "6409", "6412", "23012", "23015", "23018",
    # NOT "63012"/"64012": those are 6-series designations (NACA 63-012,
    # 64-012) and mfoil's 5-digit generator only supports the 2XY (mean-line
    # camber) family: make_mfoil(naca="63012") raises AssertionError("5-digit
    # NACA must begin with 2X0, X in 1-5"). Discovered via the Gallery's
    # airfoil-corpus thumbnails all 400ing on these two ids.
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
# /api/airfoils/upload: user-supplied .dat file (Selig or Lednicer, item 6)
# --------------------------------------------------------------------------- #


def run_airfoil_upload(filename: str, content: bytes) -> dict[str, Any]:
    """Parse an uploaded ``.dat`` file (via ``cins.cst.io.load_airfoil_dat``,
    same Selig/Lednicer autodetect as the UIUC corpus loader) and return
    geometry + a CST fit, ready to drive Analyze/FlowField/Inverse from the
    browser. Writes to a scratch temp file since ``load_airfoil_dat`` reads
    from a ``Path``: no ``src/cins`` code is touched or duplicated."""
    suffix = Path(filename).suffix or ".dat"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        try:
            X = load_airfoil_dat(tmp_path)
        except AirfoilParseError as exc:
            raise EngineError(f"could not parse {filename!r}: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    stem = Path(filename).stem or "uploaded"
    fit_result = fit_cst(X[0], X[1], n=8)
    derived = derived_geometry_quantities(
        fit_result.A_upper, fit_result.A_lower,
        fit_result.zeta_T_upper, fit_result.zeta_T_lower,
    )
    return {
        "id": f"upload:{stem}",
        "name": stem,
        "coords": X.T.tolist(),
        "n_points": int(X.shape[1]),
        "fit": {
            "A_upper": fit_result.A_upper.tolist(),
            "A_lower": fit_result.A_lower.tolist(),
            "zeta_T_upper": fit_result.zeta_T_upper,
            "zeta_T_lower": fit_result.zeta_T_lower,
            "n": fit_result.n,
            "N1": fit_result.N1,
            "N2": fit_result.N2,
            "rms": fit_result.rms,
            "gram_condition": fit_result.gram_condition,
            "derived": derived,
        },
    }


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


# Grid-size guard. With the vectorized evaluator (app.flowfield, see its
# module docstring) the per-cell cost is no longer the bottleneck: measured
# locally, `solve_inviscid` (building + factoring the ~199-panel AIC matrix,
# fixed cost independent of grid size) is ~0.24s, and even a 200x200=40000
# cell grid (FlowFieldGrid's own per-axis cap) adds only ~0.2s of vectorized
# field evaluation + ~0.35s round-trip total measured through the FastAPI
# endpoint. 24000 keeps that round trip (fixed solve cost + grid eval +
# response serialization) at ~0.4s locally, i.e. ~8s at the Render free
# tier's documented ~20x-slower-than-local rate, with margin under the ~10s
# target before the frontend's request timeout should trip.
_FLOWFIELD_MAX_CELLS = 24000


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

    # Vectorized evaluator (app.flowfield, see its module docstring): loops
    # over the ~200 airfoil panels, evaluating each panel's influence on
    # every grid point at once with numpy, instead of the old per-point
    # vendor `inviscid_velocity` call (an O(N) pure-Python loop, called
    # nx*ny times). Numerically identical: gated by
    # tests/test_flowfield_vectorized.py against the vendor function
    # directly, 1e-10 absolute.
    xg, yg = np.meshgrid(xs, ys)  # (ny, nx), matching the response's row/col layout
    xq, yq = xg.ravel(), yg.ravel()
    inside_flat = points_in_polygon(xq, yq, poly_x, poly_y)
    u_flat, v_flat = inviscid_velocity_field(X, gam, Vinf, alpha, xq, yq)
    speed_flat = np.hypot(u_flat, v_flat)
    cp_flat = 1.0 - (speed_flat / Vinf) ** 2

    inside = inside_flat.reshape(ny, nx)
    u_grid = u_flat.reshape(ny, nx)
    v_grid = v_flat.reshape(ny, nx)
    speed_grid = speed_flat.reshape(ny, nx)
    cp_grid = cp_flat.reshape(ny, nx)

    def _masked(grid: np.ndarray) -> list[list[float | None]]:
        return [
            [None if inside[j, i] else float(grid[j, i]) for i in range(nx)] for j in range(ny)
        ]

    u = _masked(u_grid)
    v = _masked(v_grid)
    speed = _masked(speed_grid)
    cp = _masked(cp_grid)

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
            # b via a closure is not possible here (rows are plain (g,b) ,
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
        # T4 presolve step (see run_inverse below): not computed standalone
        # here. Documented in app/README.md.
        "model_gap": None,
        "n_stations": int(cp_target_at_baseline.size),
    }


# --------------------------------------------------------------------------- #
# /api/inverse: stage capture for the frontend "Inverse Design Theater"
# --------------------------------------------------------------------------- #

_STAGE_DECIMATE = 80  # geometry points snapshotted per stage (item 1 of the brief)


class StageCapturingDiagnostics(NewtonDiagnostics):
    """App-side subclass of ``cins.diagnostics.recorder.NewtonDiagnostics``
    (src/cins itself is NEVER edited: see CLAUDE.md) that ADDITIONALLY
    snapshots, on every ``record_iteration`` call ``cins.solver.newton.
    solve_inverse`` makes, enough state for the frontend to animate the solve
    live: a decimated airfoil outline, current vs target Cp at the target
    stations, alpha, and the R/T/G norms already being recorded. Snapshots
    reflect mfoil's state as of the START of that Newton iteration (i.e. after
    the PREVIOUS iteration's geometry update, or the initial guess for it=0) ,
    ``solve_inverse`` calls ``record_iteration`` before applying that
    iteration's update.

    ``get_mfoil`` is a zero-arg closure returning the live ``mfoil`` instance
    ``solve_inverse`` is mutating in place (the same object passed to it) ,
    the object identity never changes mid-solve, only its internal state, so
    a closure captured once at construction stays valid for the whole run.
    """

    def __init__(
        self,
        config: CinsConfig,
        get_mfoil: Callable[[], Any],
        cp_target: np.ndarray,
        station_idx: np.ndarray,
        decimate: int = _STAGE_DECIMATE,
        on_stage: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        super().__init__(config=config)
        self._get_mfoil = get_mfoil
        self._cp_target = np.asarray(cp_target, dtype=float)
        self._station_idx = np.asarray(station_idx, dtype=int)
        self._decimate = decimate
        self._on_stage = on_stage
        self.stages: list[dict[str, Any]] = []

    def record_iteration(self, it: int, **kwargs: Any):  # noqa: ANN401 - matches base signature
        record = super().record_iteration(it, **kwargs)
        try:
            m = self._get_mfoil()
            mod = mfoil_module()
            x = np.asarray(m.foil.x[0], dtype=float)
            y = np.asarray(m.foil.x[1], dtype=float)
            n = x.size
            pick = (
                np.unique(np.linspace(0, n - 1, self._decimate).round().astype(int))
                if n > self._decimate
                else np.arange(n)
            )
            coords = np.stack([x[pick], y[pick]], axis=1).tolist()

            ue_all = np.asarray(m.glob.U[3], dtype=float)
            cp_all, _ = mod.get_cp(ue_all, m.param)
            chord = float(m.geom.chord) or 1.0

            xt = m.vsol.Xt if hasattr(m.vsol, "Xt") else None
            transition = (
                {"upper": float(xt[1, 1]), "lower": float(xt[0, 1])} if xt is not None else None
            )

            self.stages.append(
                {
                    "it": int(it),
                    "coords": coords,
                    "cp_stations_x": (x[self._station_idx] / chord).tolist(),
                    "cp_current": cp_all[self._station_idx].tolist(),
                    "cp_target": self._cp_target.tolist(),
                    "alpha": float(m.oper.alpha),
                    "R_norm": kwargs.get("R_norm"),
                    "T_norm": kwargs.get("T_norm"),
                    "G_norm": kwargs.get("G_norm"),
                    "transition": transition,
                }
            )
        except Exception:  # noqa: BLE001 - a snapshot failure must never abort the solve
            logger.exception("StageCapturingDiagnostics: snapshot failed at it=%d", it)
        if self._on_stage is not None:
            try:
                self._on_stage(self.stages)
            except Exception:  # noqa: BLE001 - progress callback must never abort the solve
                logger.exception("StageCapturingDiagnostics: on_stage callback failed")
        return record


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


def run_inverse(
    cfg: CinsConfig,
    cell_name: str = "api-inverse",
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the monolithic CST-Newton inverse solve, composed from the same
    "pipeline pieces" ``cins.benchmarks.pipeline.run_pipeline`` uses
    (``prepare_cell`` -> ``InverseProblem`` -> ``solve_inverse``), but also
    surfaces the final ``A``/coords the API needs (``run_pipeline`` itself
    only returns a ``CellResult`` with recovery-error diagnostics, not the
    final geometry). Holds ``MFOIL_LOCK`` for the whole solve (ADR-0003 +
    "one inverse at a time")."""
    t0 = time.perf_counter()
    counters = EvalCounters()

    def _phase(text: str) -> None:
        if on_progress is not None:
            on_progress(_phase_payload(text, t0))

    with MFOIL_LOCK:
        with instrument_evaluations(counters):
            # prepare_cell (cins.benchmarks.pipeline, never edited: see
            # CLAUDE.md) bundles fit -> target solve -> 2 presolve passes ->
            # station selection internally with no progress hooks, so this is
            # necessarily one coarse phase rather than the raw-target path's
            # finer-grained breakdown (run_presolve_gate_raw above).
            _phase("preparing (fit + presolve x2 + station selection)")
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
                    "stages": [],
                    "dof": None,
                }

            prob = InverseProblem(
                cp_target=prep.cp_target,
                station_surface=prep.station_surface,
                station_x=prep.station_x,
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

            def _emit_progress(stages: list[dict[str, Any]]) -> None:
                if on_progress is None:
                    return
                it = stages[-1]["it"] if stages else 0
                on_progress(
                    _phase_payload(
                        f"newton it {it}", t0, stages=stages,
                        realisability=prep.realisability, model_gap=prep.model_gap,
                        submap_cond=prep.submap_cond,
                    )
                )

            diag = StageCapturingDiagnostics(
                cfg, get_mfoil=lambda: prep.m, cp_target=prob.cp_target,
                station_idx=prep.stations, on_stage=_emit_progress,
            )
            _phase("newton it 0")
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
            "coords": coords.T.tolist(),  # (N,2): friendlier for JSON/plotting
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
            "stages": diag.stages,
            "dof": diag._dof_accounting,  # noqa: SLF001 - in-process summary, not a public API
        }


# --------------------------------------------------------------------------- #
# /api/inverse/raw: user-defined target Cp (product requirement: target
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
    ``configs/default.yaml``.

    Transition is pinned during the Newton iterations, as in the T7 protocol.
    An earlier version left it natural on the reasoning that a user-drawn
    target has no trip location to match against, but ADR-0003 is about the
    Jacobian rather than about matching a known airfoil: the e^n closure is C0
    in the design variables, so a trip that migrates between iterations puts a
    kink in the very derivatives Newton depends on. The trip is released before
    the verification solve, which reports the recovered geometry under natural
    transition.

    ``le_treatment`` is ``prescribed``, the dossier's FM-3 recommendation and
    the configuration T7/T8 use. It was ``none`` on the reasoning that a
    user-drawn target carries no nose radius to impose, and the T8 ablation
    ``t8_le_none`` did recover coefficients to 6.5e-10 without it. That
    ablation, though, selects target stations the way T8 does, restricted to
    ``x >= prescribed_le_fraction``, while this path ran unrestricted QR: with
    ``le_treatment: none`` the fraction is zero, so the two looked identical
    and were not.

    Measured on the self-consistency target, from the same perturbed start:

    ==========================  ==============  ==============
    quantity                    LE stations in  T8 recipe
    ==========================  ==============  ==============
    submap condition            --              19.9
    Newton iterations           14              8
    final residual              7.19e-11        5.06e-11
    ``|A - A*|`` inf            3.9e-2          5.4e-4
    max surface offset (mc)     0.863           0.0174
    ==========================  ==============  ==============

    The nose is taken from the presolved baseline, which is an assumption the
    caller should know about: it is reported in ``notes``."""
    base = load_config().model_dump()
    overrides: dict[str, Any] = {
        "operating": {"alpha_deg": req.alpha_deg, "Re": req.Re},
        "cst": {"n_upper": n_upper, "n_lower": n_lower, "le_treatment": "prescribed"},
        "transition": {"mode": "forced"},
        "t8": {"alpha_free": req.alpha_free},
    }
    merged = _deep_merge(base, overrides)
    return CinsConfig.model_validate(merged)


def _phase_payload(
    phase: str,
    t0: float,
    *,
    stages: list[dict[str, Any]] | None = None,
    presolve_gate: dict[str, Any] | None = None,
    realisability: float | None = None,
    model_gap: float | None = None,
    submap_cond: float | None = None,
) -> dict[str, Any]:
    """A full ``InverseResultPayload``-shaped placeholder used for progress
    updates BEFORE the Newton loop starts (fit / target solve / presolve
    passes / station selection / initial solve): same schema the growing
    ``stages`` list already uses (``_emit_progress`` below), just with a
    ``phase`` string set so the frontend can show real status text instead of
    a generic "presolving" placeholder (defect-fix: job hangs with no visible
    progress: see app/backend/app/jobs.py's module docstring)."""
    return {
        "converged": False, "iterations": len(stages or []), "alpha": None,
        "A_upper": None, "A_lower": None, "coords": None,
        "residual_history": [], "convergence_order": None,
        "release_verify": None, "realisability": realisability,
        "model_gap": model_gap, "submap_cond": submap_cond,
        "notes": [phase], "dof_check_error": None,
        "wall_time_s": time.perf_counter() - t0, "diagnostics": [],
        "manifest": None, "stages": stages or [], "dof": None,
        "presolve_gate": presolve_gate, "phase": phase,
    }


_GATE_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_GATE_CACHE_MAX = 32
_GATE_CACHE_LOCK = threading.Lock()


def run_presolve_gate_screening(req: Any, on_progress=None) -> dict[str, Any]:
    """The standalone /api/inverse/gate path: full fidelity, cached.

    Caching is the only safe saving available here. The Inverse page's common
    flow is a handful of baseline and template pairs, so the first caller pays
    for the presolve and everyone after gets it immediately. Reducing the
    presolve itself was tried and rejected; see ``run_presolve_gate_raw``.
    """
    key = hashlib.sha256(
        json.dumps(
            req.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    with _GATE_CACHE_LOCK:
        hit = _GATE_CACHE.get(key)
        if hit is not None:
            _GATE_CACHE.move_to_end(key)
            return {**hit, "cached": True}

    verdict = run_presolve_gate_raw(req, on_progress=on_progress)["gate"]
    verdict = {**verdict, "cached": False}
    with _GATE_CACHE_LOCK:
        _GATE_CACHE[key] = verdict
        _GATE_CACHE.move_to_end(key)
        while len(_GATE_CACHE) > _GATE_CACHE_MAX:
            _GATE_CACHE.popitem(last=False)
    return verdict


def run_presolve_gate_raw(
    req: Any,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    t0: float | None = None,
) -> dict[str, Any]:
    """Just the T4 gate (no Newton solve): used both standalone (so the UI
    can show the verdict before the user commits to a full inverse run) and
    as the first step of ``run_inverse_raw`` itself. ``on_progress``/``t0``
    are supplied only by ``run_inverse_raw`` (a job with phase reporting);
    the standalone ``/api/inverse/gate`` call leaves them ``None``.

    The gate is dominated by ``build_sensitivity_matrix``, which spends two
    inviscid solves per CST coefficient: at order 6 that is 29 solves per
    presolve pass, and the two passes make 60. Measured at 199 panels this is
    18.8 s locally, which on the free-tier container (33x slower, see
    ``run_analyze``) is about 620 s. That is why this call could not finish
    inside any client timeout rather than merely exceeding the one it had, and
    why the supported path is the job form plus the cache rather than a larger
    budget.

    A cheaper configuration was tried and rejected. One presolve pass at the
    interactive paneling runs 3.2x faster, and on a self-consistency target it
    agreed with the full verdict, but that agreement was luck: on a 4412 target
    against a 2412 baseline the coarse paneling and the missing pass move the
    metric in opposite directions and happen to cancel. Taken singly, one pass
    at full paneling reports 0.071 where two report 0.036, which flips the
    verdict across the 0.05 threshold. A gate that can invert its own answer to
    run faster is worse than a slow one, so both knobs stay at study fidelity.
    ``screening`` is retained only as the flag that marks the cached standalone
    path; it no longer changes any numerical setting."""
    t0 = t0 if t0 is not None else time.perf_counter()

    def _phase(text: str) -> None:
        if on_progress is not None:
            on_progress(_phase_payload(text, t0))

    _phase("fit: baseline CST fit")
    a_u0, a_l0, zeta_t_u, zeta_t_l = _baseline_from_spec(req.baseline, req.n)
    n_u, n_l = a_u0.size - 1, a_l0.size - 1
    cfg = build_inverse_raw_config(req, n_u, n_l)
    psi = cosine_spacing(_PSI_NPOINT)

    _phase("target solve: interpolating target Cp to baseline stations")
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

    n_passes = 2

    a0 = np.concatenate([a_u0, a_l0])
    # The baseline's own fitted nose, kept before the presolve passes move it.
    # When the leading edge is prescribed it must come from here rather than
    # from the presolve output: those passes are inviscid, so against a viscous
    # target they drift A_u0/A_l0 away from the baseline, and freezing a drifted
    # nose forces every remaining coefficient to compensate for it.
    a0_baseline = a0.copy()
    ps = None
    for pass_i in range(n_passes):  # mirrors prepare_cell's own init="presolve" loop
        _phase(
            f"presolve pass {pass_i + 1}/{n_passes} (inviscid Cp + sensitivity matrix)"
        )
        base_res = solve_inviscid_cp(
            a0[: n_u + 1], a0[n_u + 1 :], zeta_t_u, zeta_t_l, psi, cfg
        )
        cp_t_at_a0 = interpolate_cp_to_stations(target_res, base_res)
        rows = resolved_rows
        if not has_le_row:
            # Target-consistent closure (memory note: b = g.A*, not an idealized
            # value) using the best available proxy for A*: the presolved a0
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
        "a0_baseline": a0_baseline,
        "zeta_t_u": zeta_t_u,
        "zeta_t_l": zeta_t_l,
        "n_u": n_u,
        "n_l": n_l,
        "ps": ps,
        "t0": t0,
        "gate": {
            "realisability": ps.realisability,
            "realisable": ps.realisable,
            "npanel": int(cfg.paneling.npanel),
            "presolve_passes": int(n_passes),
            "kkt_cond": ps.kkt_cond,
            "threshold": cfg.presolve.realisability_threshold,
            "A_upper_init": a0[: n_u + 1].tolist(),
            "A_lower_init": a0[n_u + 1 :].tolist(),
        },
    }


def run_inverse_raw(
    req: Any,
    cell_name: str = "api-inverse-raw",
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """User-defined-target monolithic CST-Newton inverse solve. Runs the T4
    presolve gate first (``run_presolve_gate_raw``) and ALWAYS returns its
    verdict via ``presolve_gate``: even on an early failure: so the UI can
    surface the realisability warning regardless of what happens next.
    ``req`` is an ``app.schemas.RawTargetInverseRequest``."""
    t0 = time.perf_counter()

    def _phase(text: str) -> None:
        if on_progress is not None:
            on_progress(_phase_payload(text, t0))

    gate_ctx = run_presolve_gate_raw(req, on_progress=on_progress, t0=t0)
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
            "stages": [],
            "dof": None,
        }

    n_a = n_u + n_l + 2
    g_row, _ = shared_le_radius_row(n_u, n_l)
    has_le_row = any(c.type in ("shared_le_radius", "le_radius") for c in req.constraints)
    # Prescribed leading edge (FM-3): A_u0 and A_l0 come from the presolved
    # baseline instead of being solved for, and the shared-LE row goes with
    # them since it would otherwise constrain coefficients that are no longer
    # free. Skipped when the caller supplied their own LE constraint, which is
    # an explicit request to solve for the nose.
    prescribe_le = cfg.cst.le_treatment == "prescribed" and not has_le_row
    notes: list[str] = []
    if prescribe_le:
        fixed = {0, n_u + 1}
        free_idx = np.array([i for i in range(n_a) if i not in fixed])
        G = np.zeros((0, n_a))
        b = np.zeros(0)
        # Restore the baseline's own nose. The presolve is inviscid and drifts
        # these two coefficients when the target is viscous, and whatever value
        # they hold here is frozen for the whole solve, so it should be the
        # nose the caller's baseline actually has.
        a0 = a0.copy()
        a0[list(fixed)] = gate_ctx["a0_baseline"][list(fixed)]
        notes.append(
            "leading edge prescribed from the baseline (A_u0, A_l0 held fixed, "
            "FM-3): the solve matches the target away from the nose and does "
            "not alter the nose radius"
        )
    elif has_le_row:
        free_idx = np.arange(n_a)
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
        free_idx = np.arange(n_a)
        G = g_row.reshape(1, -1)
        b = np.array([float(g_row @ a0)])

    n_alpha = 1 if req.alpha_free else 0
    n_targets_required = len(free_idx) + n_alpha - G.shape[0]

    # Rebuild the sensitivity matrix at the FINAL presolved a0 (not the
    # pre-update pass ``ps.sensitivity`` used internally by
    # ``run_presolve_gate_raw``'s loop) so station selection and the
    # initial-guess geometry solved below are for the identical baseline ,
    # avoids the node-index drift ``prepare_cell`` guards against.
    _phase("station selection (QR pivot)")
    sens = build_sensitivity_matrix(a0[: n_u + 1], a0[n_u + 1 :], zeta_t_u, zeta_t_l, psi, cfg)
    n_pick = n_targets_required + req.n_stations_offset
    if n_pick <= 0 or n_pick > sens.x_stations.size:
        return _early([f"invalid station count requested: n_pick={n_pick}"])
    # Candidates exclude the prescribed-LE region, as T8's qr_pivot branch does
    # (cins.benchmarks.pipeline). A target row inside a region whose shape is
    # held fixed carries almost no information about the free coefficients, so
    # the square system stays formally full-rank while becoming numerically
    # near-dependent. Measured on the self-consistency target: filtering takes
    # the submap to condition 19.9 and the solve from 14 iterations at
    # |A-A*|inf 3.9e-2 to 8 iterations at 5.4e-4, with the recovered surface
    # moving from 0.863 to 0.017 millichords of the target.
    le_frac = cfg.cst.prescribed_le_fraction if cfg.cst.le_treatment == "prescribed" else 0.0
    cand = np.nonzero(np.asarray(sens.x_stations) >= le_frac)[0]
    if cand.size < n_pick:
        return _early([f"only {cand.size} candidate stations for {n_pick} requested"])
    m_cand = sens.M[cand][:, free_idx]
    _, _, piv = _qr(m_cand.T, pivoting=True)
    stations = np.sort(cand[piv[:n_pick]])

    try:
        assert_square(len(free_idx), len(stations), G.shape[0], alpha_free=req.alpha_free)
    except ValueError as exc:
        return _early(["DOF check failed"], dof_check_error=str(exc))

    # Physical (surface, x/c) station, not the a0-baseline node index (see
    # cins.solver.newton module docstring): a fixed index stops addressing the
    # same station once the geometry moves during the Newton iterations, which
    # is the ordinary case for a user-drawn target far from the baseline.
    # cp_target is interpolated directly off the target's own raw curve at
    # that x -- equivalent to (and replacing) the old
    # interpolate_cp_to_stations(...)[stations] two-step.
    station_surface, station_x = stations_from_indices(
        sens.x_stations, stations, le_idx=sens.baseline.le_idx
    )
    cp_target = interpolate_cp_at_stations(
        target_res.x, target_res.cp, station_surface, station_x
    )

    with MFOIL_LOCK:
        _phase("initial solve (viscous, presolved initial guess)")
        coords0 = coords_from_A(
            a0[: n_u + 1], a0[n_u + 1 :], zeta_t_u, zeta_t_l, psi, cfg.cst.N1, cfg.cst.N2
        )
        m = make_mfoil(coords=coords0, npanel=cfg.paneling.npanel)
        m.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
        m.solve()
        if not m.glob.conv:
            return _early(["flow solve at the presolved initial guess failed to converge"])

        # The Newton iterations run with transition pinned (ADR-0003): mfoil's
        # e^n closure is C0 in the design variables, so letting the trip migrate
        # between iterations puts a kink in the Jacobian. The pattern is frozen
        # here and released before the verification solve below, which is the
        # same order the T7 protocol uses.
        forced = cfg.transition.mode == "forced"
        if forced:
            set_forced_transition(m, cfg.transition.xtr_upper, cfg.transition.xtr_lower)
            mfoil_module().solve_coupled(m)
            if not m.glob.conv:
                release_transition()
                return _early(["flow solve failed to converge with transition pinned"])
            # model_gap below reads m.post.cp, which solve_coupled does not
            # update: without this it measured the target against the natural
            # solve's pressures rather than the tripped ones actually solved.
            refresh_post(m)

        # How far the target sits from what this viscous solve can produce.
        # The gate's realisability answers the inviscid question (ADR-0004), so
        # a target drawn in a different physical model gates as realisable and
        # then cannot be reached: this number is what makes that visible.
        cp_now = np.asarray(m.post.cp, dtype=float)[: m.foil.N]
        model_gap = float(
            np.linalg.norm(cp_now[stations] - cp_target) / max(np.linalg.norm(cp_target), 1e-12)
        )

        prob = InverseProblem(
            cp_target=cp_target,
            station_surface=station_surface,
            station_x=station_x,
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
        def _emit_progress(stages: list[dict[str, Any]]) -> None:
            if on_progress is None:
                return
            it = stages[-1]["it"] if stages else 0
            payload = _phase_payload(
                f"newton it {it}", t0, stages=stages, presolve_gate=gate,
                realisability=gate["realisability"],
            )
            on_progress(payload)

        diag = StageCapturingDiagnostics(
            cfg, get_mfoil=lambda: m, cp_target=prob.cp_target,
            station_idx=stations, on_stage=_emit_progress,
        )
        _phase("newton it 0")
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
        "model_gap": model_gap,
        "submap_cond": (
            float(np.linalg.cond(sens.M[stations][:, free_idx])) if stations.size else None
        ),
        "notes": notes,
        "dof_check_error": None,
        "wall_time_s": time.perf_counter() - t0,
        "diagnostics": diag_summary,
        "manifest": {
            "cell_name": cell_name,
            "config_hash": cfg.config_hash(),
            "cst": {
                "n_upper": n_u, "n_lower": n_l,
                "le_treatment": cfg.cst.le_treatment,
                "n_free": int(len(free_idx)),
            },
            "transition_mode": cfg.transition.mode,
        },
        "presolve_gate": gate,
        "stages": diag.stages,
        "dof": diag._dof_accounting,  # noqa: SLF001 - in-process summary, not a public API
    }


# --------------------------------------------------------------------------- #
# /api/showcase: item 7 of the brief: archived T7 run + T8 NACA panel table
# + paper figures, for the Results Gallery page and Theater's "replay
# archived T7" instant-demo button. Read-only over experiments/results/: no
# solve, no src/cins mutation; the JSON is cached in-process (same one-time-
# scan pattern as ``_scan_uiuc_cache`` above) since the underlying files never
# change while the app is running.
# --------------------------------------------------------------------------- #

_T7_DIR = REPO_ROOT / "experiments" / "results" / "t7_naca2412"
_T8_DIR = REPO_ROOT / "experiments" / "results" / "t8"
_GATES_JSON = REPO_ROOT / "site" / "gates.json"

_SHOWCASE_CACHE: dict[str, Any] | None = None


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _normalize_showcase_airfoil_id(raw: Any) -> str | None:
    """The T8 panel manifests come from two different experiment generations:
    the 117-cell UIUC sweep already stores ``t8_factors.airfoil`` as
    ``"uiuc:<name>"`` (this app's own id scheme), but the earlier H1 NACA
    panel (``experiments/results/t8/panel_0006/`` etc.) predates that
    convention and stores a bare NACA digit string (``"0006"``): passing
    that straight to ``GET /api/airfoils/{id}/geometry`` 422s (unknown
    prefix). Normalize both to this app's ``"uiuc:<name>"``/``"naca:<code>"``
    id scheme so every panel row's thumbnail resolves."""
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith(("uiuc:", "naca:")):
        return raw
    if raw.isdigit() and len(raw) in (4, 5):
        return f"naca:{raw}"
    return None


def run_showcase() -> dict[str, Any]:
    """Archived evidence for the Results Gallery: T7 self-consistency run
    (run.log numbers + diagnostics.json residual series, for Theater's replay
    button), the T8 NACA panel sweep (result.json per cell), and the gate
    board (site/gates.json): all read-only, labeled as an archived replay
    (never conflated with a live solve)."""
    global _SHOWCASE_CACHE
    if _SHOWCASE_CACHE is not None:
        return _SHOWCASE_CACHE

    t7_diag = _read_json(_T7_DIR / "diagnostics.json") or {}
    t7_log = (_T7_DIR / "run.log").read_text() if (_T7_DIR / "run.log").exists() else ""
    t7 = {
        "manifest": t7_diag.get("manifest"),
        "convergence_order": t7_diag.get("convergence_order"),
        # Combined extended-system residual sqrt(R^2+T^2+G^2) per iteration ,
        # NOT the flow-block R_norm alone, which is non-monotonic by design
        # (state re-converges after each geometry step; see the T8 analysis
        # review's warning about confusing the two series). This reproduces
        # result.json's residual_history from the archived diagnostics.
        "residual_history": [
            (
                (r.get("R_norm") or 0.0) ** 2
                + (r.get("T_norm") or 0.0) ** 2
                + (r.get("G_norm") or 0.0) ** 2
            )
            ** 0.5
            for r in t7_diag.get("iterations", [])
        ],
        "iterations": t7_diag.get("iterations", []),
        "log_tail": "\n".join(t7_log.splitlines()[-25:]),
    }

    panel: list[dict[str, Any]] = []
    if _T8_DIR.exists():
        for d in sorted(_T8_DIR.glob("panel_*")):
            r = _read_json(d / "result.json")
            if r is None:
                continue
            airfoil_id = _normalize_showcase_airfoil_id(
                (r.get("manifest") or {}).get("t8_factors", {}).get("airfoil")
            )
            panel.append(
                {
                    "cell_name": r.get("cell_name", d.name),
                    "converged": r.get("converged"),
                    "iterations": r.get("iterations"),
                    "err_all_inf": r.get("err_all_inf"),
                    "wall_time_s": r.get("wall_time_s"),
                    "notes": r.get("notes", []),
                    # lets the Gallery fetch a per-section geometry thumbnail
                    # via GET /api/airfoils/{airfoil_id}/geometry (item 7 of
                    # the app rich-features brief: "panel results with
                    # per-section thumbnails").
                    "airfoil_id": airfoil_id,
                }
            )

    figures_dir = _T8_DIR / "figures" / "paper"
    figures = (
        sorted(f"/static/figures/paper/{p.name}" for p in figures_dir.glob("*.png"))
        if figures_dir.exists()
        else []
    )

    gates = _read_json(_GATES_JSON)

    _SHOWCASE_CACHE = {
        "t7": t7,
        "panel": panel,
        "panel_n_converged": sum(1 for p in panel if p.get("converged")),
        "panel_n_total": len(panel),
        "figures": figures,
        "gates": gates,
        "manifest_note": "archived run: see git SHA / date in each entry's own manifest",
    }
    return _SHOWCASE_CACHE
