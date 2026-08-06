"""Manuscript figures derived purely from archived run artifacts.

Regenerate via::

    .venv/bin/python -m cins.benchmarks.paper_figures_archive

Unlike :mod:`cins.benchmarks.paper_figures`, nothing here re-runs a solve.
Every value plotted is read from an on-disk artifact that a reader of the
repository can open:

* ``experiments/results/t7_naca2412/{result,diagnostics}.json``
* ``experiments/results/t8/<cell>/{result,diagnostics}.json``
* ``experiments/results/t8/uiuc_panel_summary.json``
* the stratification header comment of ``configs/experiments/panel_uiuc/*.yaml``

Figures (written to ``experiments/results/t8/figures/paper/``):

``fig_cost_breakdown.png``
    Cost of the monolithic solve against its fair-paired nested
    Levenberg--Marquardt control, in three currencies side by side: counted
    flow solves, counted residual evaluations, and measured wall-clock. The
    figure exists because the three currencies do not agree, and the
    manuscript reports all three rather than the most favourable one.

``fig_convergence_orders.png``
    Residual histories of the representative runs on a logarithmic axis,
    annotated with the local three-point order estimated from the clean
    (above-floor) tail, and a companion panel showing the per-step
    contraction factor. Separates the runs whose tail is genuinely quadratic
    from the one whose tail contracts at a roughly constant rate.

``fig_uiuc_outcomes.png``
    Outcome of every section in the 117-section UIUC panel in the
    thickness--camber plane, plus the distribution of Newton iteration counts
    among converged sections. Included so that the excluded sections can be
    inspected for geometric bias rather than assumed unbiased.

Colourblind-safe (Okabe--Ito) palette, matching :mod:`cins.benchmarks.figures`.
Matplotlib Agg backend only (headless-safe).
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

C_BLUE = "#0072B2"
C_ORANGE = "#E69F00"
C_GREEN = "#009E73"
C_VERMILLION = "#D55E00"
C_PURPLE = "#CC79A7"
C_SKY = "#56B4E9"
C_GRAY = "#666666"

RESULTS_DIR = Path("experiments/results")
T8_DIR = RESULTS_DIR / "t8"
FIGURES_DIR = T8_DIR / "figures" / "paper"
UIUC_CONFIG_DIR = Path("configs/experiments/panel_uiuc")

LOG = logging.getLogger(__name__)

# Residual values at or below this magnitude are the solver's own floor: the
# finite-difference Jacobian block cannot resolve a step below it, so a local
# order estimated across such points measures rounding, not convergence.
FLOOR = 1.0e-9


def _load(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        return json.load(handle)


# --------------------------------------------------------------- cost figure

# Each pairing is (label, monolithic cell, nested-LM control cell). Both cells
# of a pairing share an initialisation strategy, which is what makes the
# comparison fair.
COST_PAIRINGS = [
    ("Pre-solve\ninitialisation", "t8_n08_baseline", "t8_n08_baseline_control"),
    ("Perturbed\n(cold) start", "t8_init_perturbed", "control_cold_control"),
]

COST_CURRENCIES = [
    ("n_flow_solves_equivalent", "Counted flow solves", ""),
    ("n_residual_evaluations", "Residual evaluations", ""),
    ("wall_time_s", "Wall-clock", " s"),
]


def fig_cost_breakdown(out: Path) -> None:
    rows = []
    for label, mono_cell, ctrl_cell in COST_PAIRINGS:
        mono = _load(T8_DIR / mono_cell / "result.json")
        ctrl = _load(T8_DIR / ctrl_cell / "result.json")
        rows.append((label, mono, ctrl))

    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.5))
    width = 0.36
    positions = np.arange(len(rows))

    for ax, (key, title, unit) in zip(axes, COST_CURRENCIES, strict=True):
        mono_vals, ctrl_vals = [], []
        for _label, mono, ctrl in rows:
            mono_vals.append(mono.get(key))
            ctrl_vals.append(ctrl.get(key))
        plotted_mono = [0.0 if v is None else float(v) for v in mono_vals]
        plotted_ctrl = [0.0 if v is None else float(v) for v in ctrl_vals]

        ax.bar(
            positions - width / 2,
            plotted_mono,
            width,
            color=C_BLUE,
            label="Monolithic",
        )
        ax.bar(
            positions + width / 2,
            plotted_ctrl,
            width,
            color=C_ORANGE,
            label="Nested LM",
        )

        headroom = max(plotted_mono + plotted_ctrl) or 1.0
        for idx, (m, c) in enumerate(zip(mono_vals, ctrl_vals, strict=True)):
            for offset, value in ((-width / 2, m), (width / 2, c)):
                if value is None:
                    ax.text(
                        positions[idx] + offset,
                        0.02 * headroom,
                        "not\nrecorded",
                        ha="center",
                        va="bottom",
                        fontsize=6.5,
                        color=C_GRAY,
                    )
                else:
                    ax.text(
                        positions[idx] + offset,
                        float(value) + 0.02 * headroom,
                        f"{value:.0f}",
                        ha="center",
                        va="bottom",
                        fontsize=7.5,
                    )
            if m is not None and c is not None and float(m) > 0:
                ax.text(
                    positions[idx],
                    0.72 * headroom,
                    f"{float(c) / float(m):.1f}x",
                    ha="center",
                    va="center",
                    fontsize=9,
                    fontweight="bold",
                    color=C_GRAY,
                )

        ax.set_xticks(positions)
        ax.set_xticklabels([label for label, _m, _c in rows], fontsize=8)
        ax.set_title(title + (f" [{unit.strip()}]" if unit else ""), fontsize=9)
        ax.set_ylim(0, 1.22 * headroom)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=8)

    axes[0].set_ylabel("count", fontsize=8)
    axes[2].set_ylabel("seconds", fontsize=8)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)
    LOG.info("wrote %s", out)


# -------------------------------------------------- convergence-order figure

# (display label, path to result.json, key holding the sequence to plot).
# The self-consistency run is plotted from its target-block history, which is
# the block its Newton iteration is actually driving; the flow block is
# already converged at its starting point.
CONVERGENCE_RUNS = [
    ("Baseline (n=8)", T8_DIR / "t8_n08_baseline" / "result.json", None, C_BLUE),
    ("Cold start", T8_DIR / "t8_init_perturbed" / "result.json", None, C_GREEN),
    ("n=6", T8_DIR / "t8_n06" / "result.json", None, C_SKY),
    ("Free incidence", T8_DIR / "t8_alpha_free" / "result.json", None, C_PURPLE),
    ("n=12", T8_DIR / "t8_n12" / "result.json", None, C_VERMILLION),
    (
        "Self-consistency run\n(interpolated stations)",
        RESULTS_DIR / "t7_naca2412" / "diagnostics.json",
        "T_norm",
        C_ORANGE,
    ),
]


def _sequence(path: Path, diagnostic_key: str | None) -> list[float]:
    payload = _load(path)
    if diagnostic_key is None:
        return [float(v) for v in payload["residual_history"]]
    return [float(it[diagnostic_key]) for it in payload["iterations"]]


def local_order(seq: list[float], floor: float = FLOOR) -> float | None:
    """Three-point local order over the last three above-floor residuals."""
    clean = [v for v in seq if v > floor]
    if len(clean) < 3:
        return None
    a, b, c = clean[-3], clean[-2], clean[-1]
    denom = math.log(b / a)
    if denom == 0.0:
        return None
    return math.log(c / b) / denom


def fig_convergence_orders(out: Path) -> None:
    fig, (ax_hist, ax_rate) = plt.subplots(1, 2, figsize=(11.0, 3.9))

    for label, path, key, colour in CONVERGENCE_RUNS:
        seq = _sequence(path, key)
        steps = np.arange(len(seq))
        order = local_order(seq)
        suffix = "" if order is None else f"  (p = {order:.2f})"
        ax_hist.semilogy(
            steps,
            seq,
            marker="o",
            markersize=3.5,
            linewidth=1.3,
            color=colour,
            label=label + suffix,
        )
        # Only steps whose two endpoints both sit above the floor carry
        # information about the convergence rate; below it the sequence is
        # measuring the finite-difference Jacobian's own noise.
        steps_above, ratios = [], []
        for k in range(len(seq) - 1):
            if seq[k] > FLOOR and seq[k + 1] > FLOOR:
                steps_above.append(k + 1)
                ratios.append(seq[k + 1] / seq[k])
        if ratios:
            ax_rate.semilogy(
                steps_above,
                ratios,
                marker="s",
                markersize=3.5,
                linewidth=1.3,
                color=colour,
            )

    ax_hist.axhspan(1e-13, FLOOR, color=C_GRAY, alpha=0.10, lw=0)
    ax_hist.text(
        0.99,
        0.03,
        "finite-difference residual floor",
        transform=ax_hist.transAxes,
        ha="right",
        va="bottom",
        fontsize=7,
        color=C_GRAY,
    )
    ax_hist.set_xlabel("Newton iteration", fontsize=9)
    ax_hist.set_ylabel("residual norm", fontsize=9)
    ax_hist.set_title("Residual history", fontsize=9)
    ax_hist.legend(fontsize=6.6, frameon=False, loc="upper right")
    ax_hist.spines[["top", "right"]].set_visible(False)
    ax_hist.tick_params(labelsize=8)

    ax_rate.set_xlabel("Newton iteration", fontsize=9)
    ax_rate.set_ylabel(r"contraction $r_{k+1}/r_k$", fontsize=9)
    ax_rate.set_title(
        "Per-step contraction above the floor:\nfalling = superlinear, flat = linear",
        fontsize=9,
    )
    ax_rate.spines[["top", "right"]].set_visible(False)
    ax_rate.tick_params(labelsize=8)

    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)
    LOG.info("wrote %s", out)


# ------------------------------------------------------- UIUC outcome figure

_STRAT = re.compile(r"thickness=([0-9.]+)\s+camber=([0-9.eE+-]+)")


def _uiuc_geometry() -> dict[str, tuple[float, float]]:
    """Section name -> (thickness/chord, camber/chord) from the config header."""
    table: dict[str, tuple[float, float]] = {}
    for path in sorted(UIUC_CONFIG_DIR.glob("panel_uiuc_*.yaml")):
        name = path.stem[len("panel_uiuc_") :]
        match = _STRAT.search(path.read_text())
        if match:
            table[name] = (float(match.group(1)), float(match.group(2)))
    return table


OUTCOME_STYLE = {
    "converged": ("recovered", C_BLUE, "o", 26),
    "over_budget": ("recovered, over iteration budget", C_SKY, "o", 30),
    "attempt_failure": ("attempt failed", C_VERMILLION, "X", 34),
    "not_posed": ("no target produced", C_GRAY, "^", 26),
}


def fig_uiuc_outcomes(out: Path) -> None:
    summary = _load(T8_DIR / "uiuc_panel_summary.json")
    geometry = _uiuc_geometry()
    budget = int(summary["gates"]["iterations_max"])

    grouped: dict[str, list[tuple[float, float]]] = {k: [] for k in OUTCOME_STYLE}
    iterations: list[int] = []
    for cell in summary["cells"]:
        name = cell["section"]
        if name not in geometry:
            continue
        if cell["converged"]:
            iters = int(cell["iterations"])
            iterations.append(iters)
            key = "converged" if iters <= budget else "over_budget"
        elif cell.get("exclusion_class") in {
            "target_natural",
            "target_forced",
            "init_flow_solve",
        }:
            key = "not_posed"
        else:
            key = "attempt_failure"
        grouped[key].append(geometry[name])

    fig, (ax_map, ax_hist) = plt.subplots(
        1, 2, figsize=(11.0, 3.9), gridspec_kw={"width_ratios": [1.35, 1.0]}
    )

    for key, (label, colour, marker, size) in OUTCOME_STYLE.items():
        pts = grouped[key]
        if not pts:
            continue
        ax_map.scatter(
            [100.0 * t for t, _c in pts],
            [100.0 * c for _t, c in pts],
            s=size,
            c=colour,
            marker=marker,
            alpha=0.85,
            linewidths=0.0,
            label=f"{label} ({len(pts)})",
        )
    ax_map.set_xlabel("maximum thickness [% chord]", fontsize=9)
    ax_map.set_ylabel("maximum camber [% chord]", fontsize=9)
    ax_map.set_title("Outcome across the UIUC panel", fontsize=9)
    ax_map.legend(fontsize=7, frameon=False, loc="upper right")
    ax_map.spines[["top", "right"]].set_visible(False)
    ax_map.tick_params(labelsize=8)

    if iterations:
        bins = np.arange(0.5, max(iterations) + 1.5, 1.0)
        ax_hist.hist(iterations, bins=bins, color=C_BLUE, alpha=0.85)
        ax_hist.axvline(budget + 0.5, color=C_VERMILLION, lw=1.4, ls="--")
        ax_hist.text(
            budget + 1.0,
            0.94,
            f"iteration budget ({budget})",
            transform=ax_hist.get_xaxis_transform(),
            fontsize=7.5,
            color=C_VERMILLION,
            va="top",
        )
    ax_hist.set_xlabel("Newton iterations to convergence", fontsize=9)
    ax_hist.set_ylabel("sections", fontsize=9)
    ax_hist.set_title("Iteration count, converged sections", fontsize=9)
    ax_hist.spines[["top", "right"]].set_visible(False)
    ax_hist.tick_params(labelsize=8)

    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)
    LOG.info("wrote %s", out)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig_cost_breakdown(FIGURES_DIR / "fig_cost_breakdown.png")
    fig_convergence_orders(FIGURES_DIR / "fig_convergence_orders.png")
    fig_uiuc_outcomes(FIGURES_DIR / "fig_uiuc_outcomes.png")


if __name__ == "__main__":
    main()
