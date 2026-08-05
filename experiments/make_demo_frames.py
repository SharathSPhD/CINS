"""Render animation frames of a live monolithic inverse solve.

Runs the T7-style monolithic pipeline (target generation + station selection,
composed from ``cins.benchmarks.pipeline.prepare_cell``'s own building blocks)
with a diagnostics recorder that captures the geometry, the pressure
distribution at the target stations, the residual norms and (post-hoc) the
inviscid flow field at every Newton iteration, then renders those stages as
video frames.

**Starting shape.** The animation needs a starting geometry that is visibly
different from the target, not a small perturbation of it (otherwise the
video shows nothing). The target is always NACA 2412 (cambered). The start is
chosen by trying, in order, the CST fit of NACA 0012 (symmetric), NACA 4412,
NACA 4415, and finally progressively closer scaled perturbations of the
target's own free coefficients -- the first candidate whose station
selection, flow convergence and full ``solve_inverse`` run all succeed is
used. Stations are physical (surface, x/c) locations
(``cins.solver.newton.stations_from_indices`` /
``interpolate_cp_at_stations``), not panel-node indices, so a starting shape
that moves the panel nodes substantially is no longer rejected: the earlier
nearest-x remap-or-fail guard existed only to patch up index correspondence
between two different geometries' paneling, and is gone along with the
node-index scheme it was patching. This mirrors ``prepare_cell``'s own steps
(station selection via QR-pivoted sensitivity, convergence-at-A0) without
editing ``src/cins/benchmarks/pipeline.py`` itself: CLAUDE.md forbids editing
``src/cins/**``, so the few steps that need a caller-supplied initial guess
(rather than ``prepare_cell``'s own presolve/perturbed/random init modes) are
re-composed here from the same public pipeline pieces
(``build_sensitivity_matrix``, ``apply_geometry``, ``assert_square``, ...).

**Flow field.** After the solve, an independent inviscid flow field
(|V|/Vinf, u, v) is computed at each captured stage's real geometry via the
same vendor ``inviscid_velocity`` approach as
``app/backend/app/engine.py::run_flowfield`` (point-in-polygon-masked grid,
one inviscid solve per stage on a *fresh* mfoil instance -- never touches the
live Newton solve's state).

The output is the centrepiece of the project demo video: a symmetric airfoil
visibly growing camber onto the cambered target while its flow field
re-accelerates over the upper surface, the sampled pressures collapse onto
the target values, and the residual falls quadratically.

Run:  .venv/bin/python experiments/make_demo_frames.py [out_dir]
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec
from scipy.linalg import qr as _qr

from cins.benchmarks.instrumentation import EvalCounters, instrument_evaluations
from cins.benchmarks.pipeline import prepare_cell
from cins.config import load_config
from cins.cst.fit import fit_cst
from cins.cst.geometry import coords_from_A
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.geometry_update import apply_geometry
from cins.solver.mfoil_adapter import make_mfoil, mfoil_module, release_transition
from cins.solver.newton import (
    InverseProblem,
    assert_square,
    interpolate_cp_at_stations,
    solve_inverse,
    stations_from_indices,
)
from cins.solver.presolve import build_sensitivity_matrix

log = logging.getLogger(__name__)

BG = "#0b1017"
FG = "#e8eef4"
MUTED = "#7d8fa1"
ACCENT = "#38bdf8"
TARGET = "#f59e0b"
GOOD = "#34d399"
GRID = "#1e2b39"

HOLD_FIRST = 45   # frames held on the starting shape
TWEEN = 46        # interpolated frames between Newton iterations
HOLD_LAST = 80    # frames held on the converged result

# Inviscid flow-field grid (item 2 of the rework brief): modest resolution,
# recomputed once per captured Newton stage (not per rendered frame -- see
# render()'s "hold the nearest stage" logic).
FLOW_NX = 90
FLOW_NY = 60
FLOW_XLIM = (-0.4, 1.4)
FLOW_YLIM = (-0.7, 0.7)

# Progressively less ambitious starting shapes, tried in order (item 1 of the
# rework brief): the target is always the fitted NACA 2412; the *first*
# candidate whose station selection + flow convergence + full solve_inverse
# run all succeed is used, so the animation shows the most distant start that
# genuinely converges.
# Ordered most-distant/most-visible first: the genuinely distant candidates
# (naca:0012 symmetric, naca:4412 twice the camber, naca:4415) lead, since
# with physical (surface, x/c) stations the panel-node-index guard that used
# to reject every one of them (measured node displacement 2.63e-3 to 5.86e-3,
# all well above the old 1e-3 hard limit) no longer applies -- see the module
# docstring. The scaled family is kept as a fallback in case a NACA start
# fails to converge for an unrelated reason (e.g. a degenerate sensitivity
# matrix).
CANDIDATE_STARTS = ["naca:0012", "naca:4412", "naca:4415", "scaled:0.5",
                    "scaled:0.65", "scaled:0.75", "scaled:0.85", "scaled:0.9", "scaled:0.94"]
START_LABELS = {
    "naca:4412": "NACA 4412 (twice the camber)",
    "naca:6412": "NACA 6412 (three times the camber)",
    "naca:2415": "NACA 2415 (thicker)",
    "naca:0012": "NACA 0012 (symmetric)",
    "naca:0009": "NACA 0009 (symmetric)",
    "naca:4415": "NACA 4415",
    "scaled:0.5": "half the target's free CST coefficients",
    "scaled:0.65": "0.65x the target's free CST coefficients",
    "scaled:0.75": "0.75x the target's free CST coefficients",
    "scaled:0.85": "0.85x the target's free CST coefficients",
    "scaled:0.9": "0.9x the target's free CST coefficients",
    "scaled:0.94": "0.94x the target's free CST coefficients",
}


def ease(t: float) -> float:
    """Smoothstep easing so the geometry motion reads as deliberate."""
    return t * t * (3.0 - 2.0 * t)


def split_surfaces(x, y):
    """Split a closed airfoil loop into lower and upper branches.

    The loop convention is TE-lower, then the leading edge, then TE-upper. Each
    branch is returned sorted by increasing x so it can be used as the sample
    grid of an interpolation.
    """
    i_le = int(np.argmin(x))
    lo_x, lo_y = x[: i_le + 1][::-1], y[: i_le + 1][::-1]
    up_x, up_y = x[i_le:], y[i_le:]
    lo = np.argsort(lo_x)
    up = np.argsort(up_x)
    return (lo_x[lo], lo_y[lo]), (up_x[up], up_y[up])


LE_MASK = 0.01  # chord fraction excluded from the surface-error panel


def surface_error(gx, gy, tx, ty):
    """Signed normal-ish offset of a geometry from a target, per surface.

    Interpolating against the whole loop is invalid because x is not monotonic
    around it; doing so returns the thickness distribution rather than the
    error. Each branch is therefore interpolated against the matching branch of
    the target.
    """
    (t_lo_x, t_lo_y), (t_up_x, t_up_y) = split_surfaces(tx, ty)
    i_le = int(np.argmin(gx))
    err = np.empty_like(gy)
    err[: i_le + 1] = gy[: i_le + 1] - np.interp(gx[: i_le + 1], t_lo_x, t_lo_y)
    err[i_le:] = gy[i_le:] - np.interp(gx[i_le:], t_up_x, t_up_y)
    return err


class StageCapture(NewtonDiagnostics):
    """Records geometry and pressure state at each Newton iteration.

    Decoupled from ``PreparedCell``: takes the physical (surface, x/c)
    stations directly, since the demo drives its own candidate starting shape
    rather than ``prepare_cell``'s built-in init modes (see module
    docstring). The "current Cp at target stations" trace is interpolated at
    those fixed x-positions on the CURRENT (moving) geometry every frame
    (``interpolate_cp_at_stations``) rather than read off a node index, which
    would drift away from the physical station as the geometry morphs from a
    visibly-distant start toward the target -- exactly the failure mode this
    whole change removes from the solver itself; the demo's own display would
    otherwise silently reintroduce it.
    """

    def __init__(self, m, station_surface, station_x, cfg):
        super().__init__(config=cfg)
        self._m = m
        self._station_surface = np.asarray(station_surface)
        self._station_x = np.asarray(station_x, dtype=float)
        self.stages: list[dict] = []

    def record_iteration(self, it: int, **kw):  # type: ignore[override]
        rec = super().record_iteration(it, **kw)
        mod = mfoil_module()
        x_now = np.asarray(self._m.foil.x[0], dtype=float)
        cp_all, _ = mod.get_cp(self._m.glob.U[3], self._m.param)
        cp_now = interpolate_cp_at_stations(
            x_now, np.asarray(cp_all), self._station_surface, self._station_x
        )
        self.stages.append(
            {
                "it": int(it),
                "x": x_now.tolist(),
                "y": np.asarray(self._m.foil.x[1]).tolist(),
                "cp_x": self._station_x.tolist(),
                "cp": cp_now.tolist(),
                "alpha": float(self._m.oper.alpha),
                "R": float(kw.get("R_norm") or 0.0),
                "T": float(kw.get("T_norm") or 0.0),
                "G": float(kw.get("G_norm") or 0.0),
            }
        )
        return rec


# --------------------------------------------------------------------------- #
# Candidate starting-shape selection (re-composed from prepare_cell's own
# building blocks -- src/cins/benchmarks/pipeline.py is never edited, so the
# steps that need a caller-supplied A0 instead of prepare_cell's built-in
# presolve/perturbed/random init are duplicated here at the call-site level).
# --------------------------------------------------------------------------- #


def _select_stations(cfg, a0, n, fit, psi, free_idx, G):
    """Mirrors prepare_cell's QR-pivoted station selection (step 5), but at a
    caller-supplied A0 rather than prepare_cell's own init. Returns
    ``(stations, sens)`` (node indices on ``sens.x_stations``, and the
    sensitivity result itself so the caller can convert those indices into
    physical (surface, x/c) stations without recomputing it), or ``(None,
    None)`` if there aren't enough candidate stations for the DOF
    requirement."""
    sens = build_sensitivity_matrix(
        a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
    )
    le_frac = cfg.cst.prescribed_le_fraction if cfg.cst.le_treatment == "prescribed" else 0.0
    n_alpha = 1 if cfg.t8.alpha_free else 0
    n_targets_required = len(free_idx) - G.shape[0] + n_alpha
    n_pick = n_targets_required + cfg.t8.dof_offset
    if cfg.t8.station_selection != "qr_pivot":
        return None, None  # demo only drives the qr_pivot default (configs/default.yaml)
    x_sens = np.asarray(sens.x_stations)
    cand = np.nonzero(x_sens >= le_frac)[0]
    if len(cand) < n_pick:
        return None, None
    m_cand = sens.M[cand][:, free_idx]
    _, _, piv = _qr(m_cand.T, pivoting=True)
    return np.sort(cand[piv[:n_pick]]), sens


def _converge_at_a0(m, a0, n, fit, psi):
    """Mirrors prepare_cell's step 6: converge the flow at A0. No remap: a
    target station is now a physical (surface, x/c) location (module
    docstring), so however far this candidate's re-paneling of A0 drifts from
    the sensitivity matrix's own paneling of A0 no longer matters for
    correctness -- only for how visibly distant a starting shape can be shown
    (which is exactly what motivated bringing the NACA starts back to the
    front of CANDIDATE_STARTS)."""
    mod = mfoil_module()
    apply_geometry(m, a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi)
    mod.solve_coupled(m)
    if not m.glob.conv:
        return "flow solve at candidate A0 failed to converge"
    return None


def attempt_candidate(cfg, code: str) -> tuple[dict | None, str]:
    """Try one candidate starting shape end-to-end (station selection ->
    convergence at A0 -> DOF check -> full solve_inverse). Returns
    ``(payload, "ok")`` on a genuine converged solve, else ``(None, reason)``.
    Never raises: a candidate failing (even via an unexpected exception from
    a pathological geometry, e.g. NACA 0009's thin sensitivity matrix) just
    means the next, less ambitious candidate is tried."""
    counters = EvalCounters()
    # A throwaway near-target init purely to obtain the shared target setup
    # (A*, target Cp, free_idx/G/b, a converged mfoil instance) cheaply and
    # reliably; this candidate's own A0 is substituted in immediately below.
    cfg_prep = cfg.model_copy(
        update={"t8": cfg.t8.model_copy(update={"init": "perturbed", "n_perturb_frac": 0.001})}
    )
    try:
        try:
            with instrument_evaluations(counters):
                prep = prepare_cell(
                    cfg_prep, counters, cell_name=f"demo-{code}", config_path=None, t0=0.0
                )
                if prep.early_failure is not None:
                    return None, f"prepare_cell early_failure: {prep.early_failure.notes}"

                n, fit = prep.n, prep.fit
                a_star, free_idx = prep.a_star, prep.free_idx
                G, b, psi = prep.G, prep.b, prep.psi
                m = prep.m
                x_target_nodes = prep.target_cp_result.x
                cp_ref = prep.target_cp_result.cp

                a0 = a_star.copy()
                if code.startswith("naca:"):
                    naca_code = code.split(":", 1)[1]
                    m_ref = make_mfoil(naca=naca_code)
                    X = m_ref.geom.xpoint
                    fit0 = fit_cst(X[0], X[1], n)
                    a0_full = np.concatenate([fit0.A_upper, fit0.A_lower])
                    a0[free_idx] = a0_full[free_idx]
                elif code.startswith("scaled:"):
                    frac = float(code.split(":", 1)[1])
                    a0[free_idx] = a_star[free_idx] * frac
                else:
                    raise ValueError(f"unknown candidate spec {code!r}")

                stations, sens = _select_stations(cfg, a0, n, fit, psi, free_idx, G)
                if stations is None:
                    return None, "station selection failed (insufficient candidate stations)"
                try:
                    assert_square(
                        len(free_idx), len(stations), G.shape[0], alpha_free=cfg.t8.alpha_free
                    )
                except ValueError as e:
                    return None, f"DOF check failed: {e}"

                # Physical (surface, x/c) station (module docstring): frozen
                # from the sensitivity matrix's own paneling of A0, and the
                # target Cp interpolated directly off the target's own curve
                # at that x -- no node-index correspondence with A0's re-panel
                # is required any more.
                station_surface, station_x = stations_from_indices(
                    sens.x_stations, stations, le_idx=sens.baseline.le_idx
                )
                cp_target_f = interpolate_cp_at_stations(
                    x_target_nodes, cp_ref, station_surface, station_x
                )

                remap_note = _converge_at_a0(m, a0, n, fit, psi)
                if remap_note is not None:
                    return None, remap_note

                # Measured, not asserted: how far A0's own re-paneling drifted
                # from the sensitivity matrix's paneling of the same A0, at
                # the selected station indices -- this is exactly the
                # quantity the old 1e-3 node-index guard rejected candidates
                # on. It is reported (not gated) to show that number is now
                # irrelevant to correctness.
                node_displacement = float(np.max(np.abs(
                    m.foil.x[0, stations] - x_target_nodes[stations]
                )))

                target = coords_from_A(
                    fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, psi
                )
                start_coords = coords_from_A(
                    a0[: n + 1], a0[n + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi
                )
                e0 = surface_error(start_coords[0], start_coords[1], target[0], target[1]) * 1000.0
                keep0 = start_coords[0] >= LE_MASK
                init_peak_mc = float(np.max(np.abs(e0[keep0])))

                prob = InverseProblem(
                    cp_target=cp_target_f,
                    station_surface=station_surface, station_x=station_x,
                    A0_upper=a0[: n + 1], A0_lower=a0[n + 1 :],
                    zeta_T_u=fit.zeta_T_upper, zeta_T_l=fit.zeta_T_lower, psi=psi,
                    G=G, b=b, free_idx=free_idx,
                    alpha0=cfg.operating.alpha_deg, alpha_free=cfg.t8.alpha_free,
                )
                diag = StageCapture(m, station_surface, station_x, cfg)
                res = solve_inverse(m, prob, cfg, diag=diag)

            if not res.converged:
                return None, (
                    f"solve_inverse did not converge within {cfg.newton.max_iter} iterations"
                )

            a_fin = np.concatenate([res.A_upper, res.A_lower])
            payload = {
                "start_code": code,
                "start_label": START_LABELS.get(code, code),
                "init_peak_error_mc": init_peak_mc,
                "node_displacement": node_displacement,
                "stages": diag.stages,
                "target_x": target[0].tolist(),
                "target_y": target[1].tolist(),
                "cp_target": np.asarray(cp_target_f).tolist(),
                "cp_target_x": np.asarray(station_x).tolist(),
                "converged": bool(res.converged),
                "iterations": int(res.iterations),
                "err_free_inf": float(np.max(np.abs(a_fin[free_idx] - a_star[free_idx]))),
                "residual_history": [float(r) for r in res.residual_norms],
            }
            return payload, "ok"
        finally:
            # Process-global forced-transition shim (ADR-0003): must be released
            # on EVERY exit path (early return or exception), or the next
            # candidate's prepare_cell call inherits stale module-level state
            # (pipeline.py's own run_pipeline uses this identical try/finally
            # pattern for the same reason).
            release_transition()
    except Exception as e:  # noqa: BLE001 - a candidate failing must never abort the sweep
        return None, f"unexpected error: {e!r}"


# --------------------------------------------------------------------------- #
# Flow field (item 2 of the rework brief): reuses the vendor inviscid_velocity
# approach app/backend/app/engine.py::run_flowfield drives, on an independent
# mfoil instance per captured stage (never touches the live Newton solve).
# --------------------------------------------------------------------------- #


def _point_in_polygon(px: float, py: float, xs: np.ndarray, ys: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test against the airfoil's closed loop
    (same algorithm as app/backend/app/engine.py's private helper of the same
    name)."""
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


def compute_flowfield(x: np.ndarray, y: np.ndarray, alpha_deg: float, cfg) -> dict:
    """Inviscid |V|/Cp field + velocity components on a modest grid around the
    CURRENT geometry (x, y): a fresh, independent mfoil instance, solved with
    solve_inviscid (never touches the live Newton solve's state)."""
    coords = np.vstack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])
    m = make_mfoil(coords=coords, npanel=cfg.paneling.npanel)
    m.setoper(alpha=alpha_deg, Ma=cfg.operating.Ma)
    mod = mfoil_module()
    mod.solve_inviscid(m)

    xs = np.linspace(FLOW_XLIM[0], FLOW_XLIM[1], FLOW_NX)
    ys = np.linspace(FLOW_YLIM[0], FLOW_YLIM[1], FLOW_NY)
    X = np.asarray(m.foil.x, dtype=float)
    gam = np.asarray(m.isol.gam, dtype=float)
    Vinf = float(m.param.Vinf)
    alpha = float(m.oper.alpha)
    poly_x, poly_y = X[0], X[1]

    u = np.full((FLOW_NY, FLOW_NX), np.nan)
    v = np.full((FLOW_NY, FLOW_NX), np.nan)
    speed = np.full((FLOW_NY, FLOW_NX), np.nan)
    for j, yy in enumerate(ys):
        for i, xx in enumerate(xs):
            if _point_in_polygon(float(xx), float(yy), poly_x, poly_y):
                continue
            vel = mod.inviscid_velocity(X, gam, Vinf, alpha, np.array([xx, yy]), False)
            uu, vv = float(vel[0]), float(vel[1])
            u[j, i] = uu
            v[j, i] = vv
            speed[j, i] = float(np.hypot(uu, vv))

    return {
        "x": xs.tolist(), "y": ys.tolist(),
        "u": u.tolist(), "v": v.tolist(), "speed": speed.tolist(),
        "vinf": Vinf,
    }


def run_capture(out_dir: Path) -> dict:
    cfg = load_config()
    payload = None
    reasons: list[str] = []
    for code in CANDIDATE_STARTS:
        payload, note = attempt_candidate(cfg, code)
        if payload is not None:
            log.info(
                "demo start candidate %s converged (%s); node_displacement=%.3e "
                "(no longer gated -- reported to show the fix works)",
                code, note, payload["node_displacement"],
            )
            print(
                f"start candidate {code}: converged ({note}); "
                f"node_displacement={payload['node_displacement']:.3e} (informational only)"
            )
            break
        log.warning("demo start candidate %s rejected: %s", code, note)
        print(f"start candidate {code}: rejected -- {note}")
        reasons.append(f"{code}: {note}")
    if payload is None:
        raise RuntimeError(
            "no candidate starting shape converged for the demo animation: "
            + "; ".join(reasons)
        )

    for st in payload["stages"]:
        st["flow"] = compute_flowfield(
            np.array(st["x"]), np.array(st["y"]), st.get("alpha", cfg.operating.alpha_deg), cfg
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stages.json").write_text(json.dumps(payload))
    return payload


def _style(ax, title=None):
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.8)
    if title:
        ax.set_title(title, color=FG, fontsize=11, pad=8, loc="left")


def render(payload: dict, out_dir: Path, width=1920, height=1080, dpi=120,
           frames_name: str = "frames") -> int:
    stages = payload["stages"]
    tx, ty = np.array(payload["target_x"]), np.array(payload["target_y"])
    cpt_x = np.array(payload["cp_target_x"])
    cpt = np.array(payload["cp_target"])
    hist = payload["residual_history"]
    start_label = payload.get("start_label", "perturbed start")

    frames_dir = out_dir / frames_name
    frames_dir.mkdir(parents=True, exist_ok=True)
    for f in frames_dir.glob("*.png"):
        f.unlink()

    seq: list[tuple[int, float]] = []
    seq += [(0, 0.0)] * HOLD_FIRST
    for i in range(len(stages) - 1):
        seq += [(i, t / TWEEN) for t in range(TWEEN)]
    seq += [(len(stages) - 1, 0.0)] * HOLD_LAST

    cp_lo = min(cpt.min(), min(min(s["cp"]) for s in stages)) - 0.25
    cp_hi = max(cpt.max(), max(max(s["cp"]) for s in stages)) + 0.25

    # Fixed y-scale for the surface-error panel, taken from the starting shape
    # so the collapse to zero is visible against a constant reference.
    x0 = np.array(stages[0]["x"])
    y0 = np.array(stages[0]["y"])
    e0 = surface_error(x0, y0, tx, ty) * 1000.0
    err_span = max(float(np.max(np.abs(e0[x0 >= LE_MASK]))) * 1.25, 0.5)

    # Flow field: precompute numpy arrays once (avoid re-parsing JSON-derived
    # lists on every one of the ~500+ rendered frames) and a fixed color scale
    # across the whole animation (a per-frame scale would flicker).
    flow_np = []
    for s in stages:
        f = s["flow"]
        flow_np.append({
            "x": np.array(f["x"], dtype=float),
            "y": np.array(f["y"], dtype=float),
            "speed": np.array(f["speed"], dtype=float),
            "u": np.ma.masked_invalid(np.array(f["u"], dtype=float)),
            "v": np.ma.masked_invalid(np.array(f["v"], dtype=float)),
            "vinf": float(f["vinf"]),
        })
    vinf_ref = float(np.mean([f["vinf"] for f in flow_np])) or 1.0
    ratio_stack = np.concatenate([f["speed"].ravel() / vinf_ref for f in flow_np])
    flow_vmin = float(np.nanmin(ratio_stack)) - 0.05
    flow_vmax = float(np.nanmax(ratio_stack)) + 0.05

    for k, (i, frac) in enumerate(seq):
        a = stages[i]
        b = stages[min(i + 1, len(stages) - 1)]
        w = ease(frac)
        gx = np.array(a["x"]) * (1 - w) + np.array(b["x"]) * w
        gy = np.array(a["y"]) * (1 - w) + np.array(b["y"]) * w
        cp = np.array(a["cp"]) * (1 - w) + np.array(b["cp"]) * w
        nearest = i if frac < 0.5 else min(i + 1, len(stages) - 1)
        fl = flow_np[nearest]

        vertical = height > width
        fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=BG)
        if vertical:
            # Five stacked panels so the animation fills a 9:16 frame instead of
            # being letterboxed inside it. Flow field placed right after the
            # geometry panel (prominent, tallest of the five).
            gs = GridSpec(5, 1, figure=fig, height_ratios=[1.0, 1.15, 0.9, 0.85, 0.65],
                          hspace=0.55, left=0.15, right=0.92, top=0.875, bottom=0.06)
            fig.text(0.5, 0.955, "Monolithic CST-Newton inverse solve",
                     color=FG, fontsize=25, fontweight="bold", ha="center")
            fig.text(0.5, 0.928, f"{start_label} -> NACA 2412 (target)",
                     color=MUTED, fontsize=14, ha="center")
            fig.text(0.5, 0.905, f"Newton iteration {a['it']}",
                     color=ACCENT, fontsize=17, ha="center", family="monospace")
        else:
            # Geometry and flow field share the prominent top row; pressure and
            # surface error share the middle row; residual spans the bottom.
            gs = GridSpec(3, 2, figure=fig, height_ratios=[1.25, 1.0, 0.55],
                          hspace=0.40, wspace=0.24,
                          left=0.05, right=0.965, top=0.86, bottom=0.075)
            fig.text(0.06, 0.945, "Monolithic CST-Newton inverse solve",
                     color=FG, fontsize=21, fontweight="bold")
            fig.text(0.06, 0.905,
                     f"{start_label}  ->  NACA 2412 (target). "
                     "No optimizer, no surrogate.", color=MUTED, fontsize=12)
            fig.text(0.97, 0.945, f"Newton iteration {a['it']}",
                     color=ACCENT, fontsize=15, ha="right", family="monospace")

        ax1 = fig.add_subplot(gs[0, 0])
        _style(ax1, "Geometry: current shape against the target")
        ax1.plot(tx, ty, color=TARGET, lw=3.0, alpha=0.5, label="target", zorder=2)
        ax1.plot(gx, gy, color=ACCENT, lw=2.0, label="current", zorder=3)
        ax1.set_xlim(-0.03, 1.03)
        ax1.set_ylim(-0.16, 0.19)
        ax1.set_aspect("equal", adjustable="box")
        ax1.set_xlabel("x / c", color=MUTED, fontsize=10)
        leg = ax1.legend(loc="upper right", frameon=True, fontsize=10,
                         facecolor=BG, edgecolor=GRID, framealpha=0.95)
        for t in leg.get_texts():
            t.set_color(FG)

        ax_flow = fig.add_subplot(gs[1, 0] if vertical else gs[0, 1])
        _style(ax_flow, "Inviscid flow field: |V| / V∞")
        ratio_field = fl["speed"] / fl["vinf"]
        pcm = ax_flow.pcolormesh(fl["x"], fl["y"], ratio_field, shading="auto",
                                  cmap="plasma", vmin=flow_vmin, vmax=flow_vmax, zorder=1)
        ax_flow.streamplot(fl["x"], fl["y"], fl["u"], fl["v"], color=(1, 1, 1, 0.55),
                           linewidth=0.6, density=1.0, arrowsize=0.6, zorder=2)
        ax_flow.fill(gx, gy, color=BG, zorder=3)
        ax_flow.plot(gx, gy, color=ACCENT, lw=1.6, zorder=4)
        ax_flow.set_xlim(*FLOW_XLIM)
        ax_flow.set_ylim(*FLOW_YLIM)
        ax_flow.set_aspect("equal", adjustable="box")
        ax_flow.set_xlabel("x / c", color=MUTED, fontsize=10)
        cb = fig.colorbar(pcm, ax=ax_flow, fraction=0.045, pad=0.02)
        cb.ax.tick_params(colors=MUTED, labelsize=8)
        cb.outline.set_edgecolor(GRID)

        ax2 = fig.add_subplot(gs[2, 0] if vertical else gs[1, 0])
        _style(ax2, "Pressure at the selected stations")
        ax2.scatter(cpt_x, cpt, s=48, facecolors="none", edgecolors=TARGET,
                    linewidths=1.8, label="target", zorder=3)
        ax2.scatter(cpt_x, cp, s=22, color=ACCENT, label="current", zorder=4)
        for xx, c0, c1 in zip(cpt_x, cp, cpt):
            ax2.plot([xx, xx], [c0, c1], color=MUTED, lw=0.9, alpha=0.7, zorder=2)
        ax2.set_ylim(cp_hi, cp_lo)
        ax2.set_xlim(-0.03, 1.03)
        ax2.set_xlabel("x / c", color=MUTED, fontsize=10)
        ax2.set_ylabel("$C_p$ (inverted)", color=MUTED, fontsize=10)
        leg2 = ax2.legend(loc="lower right", frameon=True, fontsize=9,
                          facecolor=BG, edgecolor=GRID, framealpha=0.95)
        for t in leg2.get_texts():
            t.set_color(FG)

        axm = fig.add_subplot(gs[3, 0] if vertical else gs[1, 1])
        _style(axm, "Surface error against the target, magnified")
        dy = surface_error(gx, gy, tx, ty) * 1000.0
        keep = gx >= LE_MASK
        gx_e, dy = gx[keep], dy[keep]
        axm.fill_between(gx_e, 0, dy, color=ACCENT, alpha=0.35, zorder=2)
        axm.plot(gx_e, dy, color=ACCENT, lw=1.4, zorder=3)
        axm.axhline(0.0, color=TARGET, lw=1.6, alpha=0.7, zorder=4)
        axm.set_xlim(-0.03, 1.03)
        axm.set_ylim(-err_span, err_span)
        axm.set_xlabel("x / c", color=MUTED, fontsize=10)
        axm.set_ylabel("surface offset (millichords)", color=MUTED, fontsize=10)
        axm.text(0.02, 0.92, f"peak {np.max(np.abs(dy)):.3f} mc",
                 transform=axm.transAxes, color=FG, fontsize=10, family="monospace")
        axm.text(0.02, 0.06,
                 f"x/c < {LE_MASK:g} excluded: vertical offset is not a\n"
                 "meaningful error where the surface is vertical",
                 transform=axm.transAxes, color=MUTED, fontsize=7.5)

        ax3 = fig.add_subplot(gs[4, 0] if vertical else gs[2, :])
        _style(ax3, "Residual norm per iteration")
        shown = hist[: a["it"] + 1] if a["it"] + 1 <= len(hist) else hist
        ax3.semilogy(range(len(shown)), shown, color=GOOD, lw=2.2,
                     marker="o", markersize=6)
        ax3.set_xlim(-0.3, max(len(hist) - 0.7, 1))
        ax3.set_ylim(min(hist) * 0.25, max(hist) * 4)
        ax3.set_xlabel("Newton iteration", color=MUTED, fontsize=10)
        ax3.set_ylabel(r"$\|R\|$", color=MUTED, fontsize=10)
        if shown:
            ax3.text(0.97, 0.06, f"{shown[-1]:.2e}", transform=ax3.transAxes,
                     color=GOOD, fontsize=12, family="monospace", ha="right")

        if k >= len(seq) - HOLD_LAST:
            fig.text(0.5, 0.022 if vertical else 0.028,
                     f"Recovered to {payload['err_free_inf']:.2e} in "
                     f"{payload['iterations']} Newton iterations",
                     color=GOOD, fontsize=15, ha="center", fontweight="bold")

        fig.savefig(frames_dir / f"f{k:05d}.png", facecolor=BG)
        plt.close(fig)

    return len(seq)


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path("experiments/results/demo")
    cache = out_dir / "stages.json"
    if cache.exists() and "--reuse" in argv:
        payload = json.loads(cache.read_text())
    else:
        payload = run_capture(out_dir)
    n = render(payload, out_dir)
    nv = render(payload, out_dir, width=1080, height=1920, frames_name="frames_vertical")
    print(f"captured {len(payload['stages'])} stages, rendered {n} wide "
          f"and {nv} vertical frames -> {out_dir}")
    print(f"start={payload.get('start_label')} "
          f"init_peak_error_mc={payload.get('init_peak_error_mc')} "
          f"node_displacement={payload.get('node_displacement')}")
    print(f"converged={payload['converged']} iters={payload['iterations']} "
          f"err={payload['err_free_inf']:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
