"""Paper P1 deepening-pass evidence figures (geometry, Cp, flow solution, H1
panel gallery). Regenerate via::

    .venv/bin/python -m cins.benchmarks.paper_figures

Everything here is derived by RE-RUNNING the monolithic inverse pipeline --
never from hand-entered numbers (SPEC.md §9, "Do not"). Neither
``experiments/results/t7_naca2412/diagnostics.json`` nor any
``experiments/results/t8/*/result.json`` stores the CST coefficient vectors
or Cp/boundary-layer distributions themselves (only scalar summaries), so the
geometry/Cp/flow-solution figures require one fresh monolithic solve per
airfoil -- exactly ``experiments/run_t7.py``'s config for the T7 winning
configuration, and 6 representative ``configs/experiments/panel_naca/*.yaml``
overlays for the H1 panel gallery. All scalar annotations (err_all_inf,
iteration counts) are still read verbatim from the on-disk
``experiments/results/t8/panel_*/result.json`` artifacts, never recomputed,
so a figure's annotation always matches the gate-closure record.

Figures (written to ``experiments/results/t8/figures/paper/``):
    fig_t7_geometry_overlay.png  -- target vs. recovered airfoil shape (T7
        winning config), LE-region inset, coefficient-error bar chart.
    fig_t7_cp_comparison.png     -- target vs. recovered Cp: full curve
        (inverted y-axis, aero convention) and the 16 QR-pivoted stations.
    fig_t7_flow_solution.png     -- Cp + displacement-thickness distribution
        of the converged (release-and-verify, natural-transition) solve.
    fig_h1_panel_gallery.png     -- 6-airfoil small-multiples of recovered
        H1 panel sections (thin/thick/cambered), each annotated with its
        err_all_inf from the corresponding experiments/results/t8/panel_*/
        result.json.

Colorblind-safe (Okabe-Ito) palette, matching ``cins.benchmarks.figures``.
Matplotlib Agg backend only (headless-safe).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from cins.benchmarks.instrumentation import EvalCounters, instrument_evaluations
from cins.benchmarks.pipeline import PreparedCell, prepare_cell
from cins.config import CinsConfig, load_config
from cins.cst.geometry import coords_from_A
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.mfoil_adapter import make_mfoil, release_transition
from cins.solver.newton import InverseProblem, InverseResult, solve_inverse

C_BLUE = "#0072B2"
C_ORANGE = "#E69F00"
C_GREEN = "#009E73"
C_VERMILLION = "#D55E00"
C_GRAY = "#666666"

RESULTS_DIR = Path("experiments/results/t8")
FIGURES_DIR = RESULTS_DIR / "figures" / "paper"

# 6 representative H1 panel cells: thin, thick, moderately-cambered baseline,
# thick-cambered, NACA5 (reflex-camber family), and high-camber. All 6 are
# among the 17/19 generable panel_* cells actually run (H1 closure commit
# "18/18 generable sections recovered"; panel_0006, panel_44012 are the two
# non-generable cells and are intentionally excluded here).
H1_GALLERY_CELLS = ["0009", "0025", "2412", "4415", "23012", "6412"]

log = logging.getLogger(__name__)


def _t7_config() -> CinsConfig:
    """The T7 winning configuration is exactly ``configs/default.yaml``
    (experiments/run_t7.py's own comment: "same config ... unmodified")."""
    return load_config()


class SolvedCell:
    """Everything a figure needs from one monolithic-inverse re-run: target
    and recovered coefficient vectors, both geometries, target/recovered Cp
    (forced-transition, the state the Newton solve actually matched), and
    the natural-transition release-and-verify solve (for the flow-solution
    figure's boundary-layer distribution)."""

    def __init__(self, cfg: CinsConfig, prep: PreparedCell, res: InverseResult, m_forced: Any):
        self.cfg = cfg
        self.prep = prep
        self.res = res
        self.a_star = prep.a_star
        self.a_final = np.concatenate([res.A_upper, res.A_lower])
        self.n = prep.n
        self.psi = prep.psi
        self.zeta_T_u = prep.fit.zeta_T_upper
        self.zeta_T_l = prep.fit.zeta_T_lower
        self.stations = prep.stations
        self.cp_target_stations = prep.cp_target
        # Full-curve target Cp (forced transition; the target the solve saw).
        # mfoil's post.cp/post.ds carry wake nodes appended after the N
        # airfoil-surface nodes (post.cp has len N+Nwake, foil.x has len N;
        # docs/mfoil_internals.md); truncate to the airfoil surface for
        # every full-curve plot. Station indices index the SAME array and
        # are < N by construction (prepare_cell candidate selection), so
        # they need no truncation.
        n_foil = prep.m.foil.N
        self.x_target_full = prep.target_cp_result.x[:n_foil]
        self.cp_target_full = prep.target_cp_result.cp[:n_foil]
        # Full-curve recovered Cp, same (forced) transition mode, straight
        # from the converged Newton state -- before release-and-verify.
        self.x_recovered_full = np.asarray(m_forced.foil.x[0]).copy()
        self.cp_recovered_full = np.asarray(m_forced.post.cp).copy()[:n_foil]

        # Release-and-verify: natural transition at the recovered geometry
        # (ADR-0003 mandate). This IS "the converged solve" for the flow-
        # solution figure -- released, physically realistic boundary layer.
        release_transition()
        coords = coords_from_A(res.A_upper, res.A_lower, self.zeta_T_u, self.zeta_T_l, prep.psi)
        m_ver = make_mfoil(coords=coords)
        m_ver.setoper(alpha=cfg.operating.alpha_deg, Re=cfg.operating.Re)
        m_ver.solve()
        self.m_verify = m_ver
        n_foil_ver = m_ver.foil.N
        self.x_verify = np.asarray(m_ver.foil.x[0]).copy()
        self.cp_verify = np.asarray(m_ver.post.cp).copy()[:n_foil_ver]
        self.ds_verify = np.asarray(m_ver.post.ds).copy()[:n_foil_ver]

    def coords_target(self) -> np.ndarray:
        return coords_from_A(
            self.a_star[: self.n + 1], self.a_star[self.n + 1 :],
            self.zeta_T_u, self.zeta_T_l, self.psi,
        )

    def coords_recovered(self) -> np.ndarray:
        return coords_from_A(
            self.a_final[: self.n + 1], self.a_final[self.n + 1 :],
            self.zeta_T_u, self.zeta_T_l, self.psi,
        )


def run_monolithic_cell(cfg: CinsConfig, cell_name: str) -> SolvedCell:
    """One fresh monolithic-inverse solve (prepare_cell + solve_inverse),
    matching ``cins.benchmarks.pipeline.run_pipeline`` step-for-step but
    keeping the intermediate arrays a figure needs instead of discarding
    them into a scalar ``CellResult``."""
    counters = EvalCounters()
    try:
        with instrument_evaluations(counters):
            prep = prepare_cell(cfg, counters, cell_name=cell_name)
            if prep.early_failure is not None:
                raise RuntimeError(
                    f"{cell_name}: prepare_cell early-failed: {prep.early_failure.notes}"
                )
            prob = InverseProblem(
                cp_target=prep.cp_target,
                station_surface=prep.station_surface, station_x=prep.station_x,
                A0_upper=prep.a0[: prep.n + 1], A0_lower=prep.a0[prep.n + 1 :],
                zeta_T_u=prep.fit.zeta_T_upper, zeta_T_l=prep.fit.zeta_T_lower, psi=prep.psi,
                G=prep.G, b=prep.b, free_idx=prep.free_idx, alpha0=cfg.operating.alpha_deg,
                alpha_free=cfg.t8.alpha_free,
            )
            diag = NewtonDiagnostics(config=cfg)
            res = solve_inverse(prep.m, prob, cfg, diag=diag)
            log.info(
                "%s: converged=%s iters=%d err_all_inf=%.3e",
                cell_name, res.converged, res.iterations,
                float(np.max(np.abs(
                    np.concatenate([res.A_upper, res.A_lower]) - prep.a_star
                ))),
            )
            solved = SolvedCell(cfg, prep, res, prep.m)
    finally:
        release_transition()
    return solved


def _panel_result_json(naca: str) -> dict[str, Any]:
    path = RESULTS_DIR / f"panel_{naca}" / "result.json"
    with path.open() as f:
        return json.load(f)


# ------------------------------------------------------------------ fig (a)


def fig_t7_geometry_overlay(cell: SolvedCell, out_dir: Path) -> Path:
    target = cell.coords_target()
    recovered = cell.coords_recovered()
    coeff_err = np.abs(cell.a_final - cell.a_star)
    n = cell.n
    labels = [f"$A_{{u,{i}}}$" for i in range(n + 1)] + [f"$A_{{l,{i}}}$" for i in range(n + 1)]
    prescribed = {0, n + 1}

    fig = plt.figure(figsize=(9, 6.2))
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1])
    ax_geo = fig.add_subplot(gs[0])

    ax_geo.plot(target[0], target[1], color=C_BLUE, lw=2.4, label="target ($A^*$)")
    ax_geo.plot(
        recovered[0], recovered[1], color=C_VERMILLION, lw=1.1, ls="--",
        label="recovered ($A$, Newton-converged)",
    )
    ax_geo.set_aspect("equal")
    ax_geo.set_xlabel(r"$x/c$")
    ax_geo.set_ylabel(r"$z/c$")
    ax_geo.set_title(
        "T7 winning configuration: target vs.\\ recovered geometry "
        f"(NACA {cell.cfg.t8.airfoil}, $n={n}$/side)"
    )
    ax_geo.legend(loc="lower right", frameon=False, fontsize=8)

    # LE-region inset: the region the T7 report identifies as where Newton
    # geometrically wanders (FM-3), and where 2/(2n+2) coefficients are
    # prescribed rather than recovered.
    ax_inset = ax_geo.inset_axes([0.45, 0.05, 0.3, 0.55])
    le_mask = np.abs(target[0]) < 0.06
    ax_inset.plot(target[0][le_mask], target[1][le_mask], color=C_BLUE, lw=2.4)
    ax_inset.plot(
        recovered[0][le_mask], recovered[1][le_mask], color=C_VERMILLION, lw=1.1, ls="--"
    )
    ax_inset.set_xlim(-0.005, 0.06)
    ax_inset.set_title("LE region", fontsize=8)
    ax_inset.tick_params(labelsize=7)
    ax_geo.indicate_inset_zoom(ax_inset, edgecolor=C_GRAY)

    ax_bar = fig.add_subplot(gs[1])
    colors = [C_GRAY if i in prescribed else C_GREEN for i in range(len(coeff_err))]
    floor = 1e-16
    ax_bar.bar(range(len(coeff_err)), np.maximum(coeff_err, floor), color=colors)
    ax_bar.set_yscale("log")
    ax_bar.set_xticks(range(len(coeff_err)))
    ax_bar.set_xticklabels(labels, rotation=90, fontsize=7)
    ax_bar.axhline(1e-4, color=C_ORANGE, ls=":", lw=1.2, label=r"T7 gate ($10^{-4}$)")
    ax_bar.set_ylabel(r"$|A_i - A_i^*|$")
    ax_bar.set_title(
        "Per-coefficient recovery error (gray = prescribed by le\\_treatment, "
        "not Newton-recovered)"
    )
    ax_bar.legend(loc="upper right", frameon=False, fontsize=8)

    fig.tight_layout()
    out = out_dir / "fig_t7_geometry_overlay.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


# ------------------------------------------------------------------ fig (b)


def fig_t7_cp_comparison(cell: SolvedCell, out_dir: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    ax = axes[0]
    ax.plot(
        cell.x_target_full, cell.cp_target_full, color=C_BLUE, lw=1.8,
        label="target $C_p$ (forced transition)",
    )
    ax.plot(
        cell.x_recovered_full, cell.cp_recovered_full, color=C_VERMILLION, lw=1.0, ls="--",
        label="recovered-geometry $C_p$",
    )
    ax.invert_yaxis()
    ax.set_xlabel(r"$x/c$")
    ax.set_ylabel(r"$C_p$")
    ax.set_title("Full-curve $C_p$ (forced-transition, Newton-converged)")
    ax.legend(loc="lower right", frameon=False, fontsize=8)

    ax2 = axes[1]
    order = np.argsort(cell.x_recovered_full[cell.stations])
    xs = cell.x_recovered_full[cell.stations][order]
    cp_t = cell.cp_target_stations[order]
    cp_r = cell.cp_recovered_full[cell.stations][order]
    ax2.plot(xs, cp_t, "o", color=C_BLUE, ms=6, label="target (16 QR stations)")
    ax2.plot(xs, cp_r, "x", color=C_VERMILLION, ms=7, mew=1.5, label="recovered")
    ax2.invert_yaxis()
    ax2.set_xlabel(r"$x/c$")
    ax2.set_ylabel(r"$C_p$")
    ax2.set_title("QR-pivoted target stations only ($M=16$)")
    ax2.legend(loc="lower right", frameon=False, fontsize=8)

    fig.suptitle(
        f"T7 winning configuration -- $C_p$ comparison "
        f"(NACA {cell.cfg.t8.airfoil}, $\\|A-A^*\\|_\\infty="
        f"{np.max(np.abs(cell.a_final - cell.a_star)):.2e}$)"
    )
    fig.tight_layout()
    out = out_dir / "fig_t7_cp_comparison.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


# ------------------------------------------------------------------ fig (c)


def fig_t7_flow_solution(cell: SolvedCell, out_dir: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    ax = axes[0]
    ax.plot(cell.x_verify, cell.cp_verify, color=C_BLUE, lw=1.8)
    ax.invert_yaxis()
    ax.set_xlabel(r"$x/c$")
    ax.set_ylabel(r"$C_p$")
    ax.set_title("$C_p$ (natural-transition release-and-verify solve)")

    ax2 = axes[1]
    ax2.plot(cell.x_verify, cell.ds_verify, color=C_GREEN, lw=1.8)
    ax2.set_xlabel(r"$x/c$")
    ax2.set_ylabel(r"$\delta^*/c$ (displacement thickness)")
    ax2.set_title("Boundary-layer displacement thickness")

    m = cell.m_verify
    fig.suptitle(
        f"Converged flow solution at recovered geometry "
        f"(NACA {cell.cfg.t8.airfoil}: $c_l={m.post.cl:.4f}$, $c_d={m.post.cd:.5f}$, "
        f"release-and-verify $\\Delta c_l={abs(m.post.cl - cell.prep.nat_cl):.1e}$)"
    )
    fig.tight_layout()
    out = out_dir / "fig_t7_flow_solution.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


# ------------------------------------------------------------------ fig (d)


def fig_h1_panel_gallery(out_dir: Path, cells: list[str] | None = None) -> Path:
    cells = cells if cells is not None else H1_GALLERY_CELLS
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.2))
    for ax, naca in zip(axes.ravel(), cells, strict=True):
        cfg = load_config(f"configs/experiments/panel_naca/panel_{naca}.yaml")
        solved = run_monolithic_cell(cfg, f"paperfig_panel_{naca}")
        target = solved.coords_target()
        recovered = solved.coords_recovered()
        rec = _panel_result_json(naca)

        ax.plot(target[0], target[1], color=C_BLUE, lw=2.0, label="target")
        ax.plot(recovered[0], recovered[1], color=C_VERMILLION, lw=0.9, ls="--", label="recovered")
        ax.set_aspect("equal")
        ax.set_title(f"NACA {naca}", fontsize=10)
        ax.text(
            0.02, 0.05,
            f"err={rec['err_all_inf']:.2e}\niters={rec['iterations']}",
            transform=ax.transAxes, fontsize=7.5, va="bottom",
            bbox={"boxstyle": "round", "fc": "white", "ec": C_GRAY, "alpha": 0.85},
        )
        ax.tick_params(labelsize=7)
    axes.ravel()[0].legend(loc="upper right", frameon=False, fontsize=7)
    fig.suptitle(
        "H1 panel gallery: 6 representative recovered sections "
        "(thin/thick/cambered), target vs.\\ recovered. Source: "
        "experiments/results/t8/panel_*/result.json"
    )
    fig.tight_layout()
    out = out_dir / "fig_h1_panel_gallery.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Re-running T7 winning configuration for figures (a)-(c) ...")
    cell = run_monolithic_cell(_t7_config(), "paperfig_t7")
    p1 = fig_t7_geometry_overlay(cell, FIGURES_DIR)
    p2 = fig_t7_cp_comparison(cell, FIGURES_DIR)
    p3 = fig_t7_flow_solution(cell, FIGURES_DIR)
    log.info("wrote %s, %s, %s", p1, p2, p3)

    log.info("Re-running %d H1 panel cells for figure (d) ...", len(H1_GALLERY_CELLS))
    p4 = fig_h1_panel_gallery(FIGURES_DIR)
    log.info("wrote %s", p4)


if __name__ == "__main__":
    main()
