"""T8 ablation figures (STATS_PROTOCOL, ADR-0004 reporting rules).

Regenerates the four T8 figures directly from ``experiments/results/t8/*/result.json``
and ``diagnostics.json`` -- no hand-entered numbers (STATS_PROTOCOL §7). Run as::

    .venv/bin/python -m cins.benchmarks.figures

Figures:
    (a) fig_h3_convergence_overlay -- D-6 residual overlay, headline cells, log scale.
    (b) fig_n_sweep -- iterations + err vs n (twin axis) plus the conditioning context
        (T2 Gram conditioning, T8 submap conditioning, T6 D-2 extended-system conditioning),
        each of which is a DIFFERENT matrix per ADR-0004 and must never be conflated.
    (c) fig_h2_flow_solves -- flow-solve-count bar chart, monolithic vs warm-started LM
        control vs cold-start LM control (if available), honest (non-truncated) axis.
    (d) fig_station_selection -- err_all_inf comparison, qr_pivot vs evenly-spaced
        stations, annotated with submap conditioning (the identifiability finding,
        docs/triz/T7-identifiability.md).

Colorblind-safe palette (Okabe-Ito), Matplotlib Agg backend only (headless-safe).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

RESULTS_DIR = Path("experiments/results/t8")
T2_COND_PATH = Path("experiments/results/t2_gram_conditioning.json")
FIGURES_DIR = RESULTS_DIR / "figures"

# Okabe-Ito colorblind-safe palette.
C_BLUE = "#0072B2"
C_ORANGE = "#E69F00"
C_GREEN = "#009E73"
C_VERMILLION = "#D55E00"
C_PURPLE = "#CC79A7"
C_SKY = "#56B4E9"
C_YELLOW = "#F0E442"
C_GRAY = "#666666"

FLOOR = 1e-9  # FD-noise floor (STATS_PROTOCOL §2 H3 method note)


def _load(cell: str) -> dict[str, Any]:
    with (RESULTS_DIR / cell / "result.json").open() as f:
        return json.load(f)


def _load_diag(cell: str) -> dict[str, Any] | None:
    path = RESULTS_DIR / cell / "diagnostics.json"
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def fig_h3_convergence_overlay(out_path: Path = FIGURES_DIR / "h3_convergence_overlay.png") -> Path:
    """D-6 overlay: log residual vs Newton iteration for the headline cells.

    baseline (qr_pivot, n=8, converges to the correct root) vs station_even
    (converges but to the WRONG root, err_all_inf=1.4e-3 >> gate 1e-4) vs n12
    (FM-2 conditioning cliff, 21 iterations vs the panel's typical 3-5).
    """
    cells = {
        "baseline (n=8, qr_pivot)": ("t8_n08_baseline", C_BLUE, "-o"),
        "station_even (WRONG ROOT)": ("t8_station_even", C_VERMILLION, "-s"),
        "n12 (FM-2 cliff, 21 it.)": ("t8_n12", C_ORANGE, "-^"),
    }
    fig, ax = plt.subplots(figsize=(7.0, 4.5))
    for label, (cell, color, style) in cells.items():
        r = _load(cell)
        hist = r["residual_history"]
        ax.plot(
            range(len(hist)), hist, style, color=color, label=label, markersize=5, linewidth=1.6
        )
    ax.axhline(FLOOR, color=C_GRAY, linestyle=":", linewidth=1.2, label="FD-noise floor (~1e-9)")
    ax.axhline(
        1e-4, color="black", linestyle="--", linewidth=1.0, label="H1 gate (err_all_inf < 1e-4)"
    )
    ax.set_yscale("log")
    ax.set_xlabel("Newton iteration")
    ax.set_ylabel(r"Newton residual $\|R\|_\infty$ (D-6)")
    ax.set_title("T8 headline cells: Newton residual history (log scale)")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def fig_n_sweep(out_path: Path = FIGURES_DIR / "n_sweep.png") -> Path:
    """Iterations + err_all_inf vs n (twin axis), plus a conditioning-context panel.

    The conditioning panel plots THREE distinct matrices' conditioning (ADR-0004:
    never conflate these) -- T2's Bernstein/Gram fit conditioning, T8's QR-selected
    station submap conditioning, and T6 D-2's full extended-Newton-system Jacobian
    conditioning (first-iteration cond_J per cell) -- each answering a different
    question about the n-sweep (FM-2).
    """
    n_cells = {4: "t8_n04", 6: "t8_n06", 8: "t8_n08_baseline", 10: "t8_n10", 12: "t8_n12"}
    ns = sorted(n_cells)
    iters, errs, submap_cond, extended_cond = [], [], [], []
    for n in ns:
        r = _load(n_cells[n])
        iters.append(r["iterations"])
        errs.append(r["err_all_inf"])
        submap_cond.append(r["submap_cond"])
        diag = _load_diag(n_cells[n])
        extended_cond.append(diag["iterations"][0]["cond_J"] if diag else None)

    t2_cond_by_n: dict[int, float] = {}
    if T2_COND_PATH.exists():
        with T2_COND_PATH.open() as f:
            t2 = json.load(f)
        for rec in t2["records"]:
            if rec["airfoil"] == "2412":
                t2_cond_by_n[rec["n"]] = rec["cond"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.5))

    ax1.plot(ns, iters, "-o", color=C_BLUE, label="Newton iterations")
    ax1.set_xlabel("Bernstein order n (per side)")
    ax1.set_ylabel("Newton iterations", color=C_BLUE)
    ax1.tick_params(axis="y", labelcolor=C_BLUE)
    ax1.axhline(9, color=C_BLUE, linestyle=":", linewidth=1.0, alpha=0.7)
    ax1.text(ns[0], 9.4, "H1 gate: max 9 iters", fontsize=7, color=C_BLUE)

    ax1b = ax1.twinx()
    ax1b.plot(ns, errs, "-s", color=C_VERMILLION, label=r"$\|A-A^*\|_\infty$")
    ax1b.set_yscale("log")
    ax1b.set_ylabel(r"$\|A-A^*\|_\infty$", color=C_VERMILLION)
    ax1b.tick_params(axis="y", labelcolor=C_VERMILLION)
    ax1b.axhline(1e-4, color=C_VERMILLION, linestyle="--", linewidth=1.0, alpha=0.7)
    ax1.set_title("n-sweep: iterations & recovery error (FM-2)")
    ax1.grid(True, alpha=0.25)

    ax2.plot(ns, submap_cond, "-o", color=C_GREEN, label="T7/T8 submap cond (qr_pivot)")
    if all(v is not None for v in extended_cond):
        ax2.plot(ns, extended_cond, "-^", color=C_PURPLE, label="T6 D-2 extended-system cond_J")
    if t2_cond_by_n:
        t2_ns = sorted(t2_cond_by_n)
        ax2.plot(
            t2_ns,
            [t2_cond_by_n[n] for n in t2_ns],
            "-s",
            color=C_ORANGE,
            label="T2 Gram/fit cond (context, NACA 2412)",
        )
    ax2.set_yscale("log")
    ax2.set_xlabel("Bernstein order n (per side)")
    ax2.set_ylabel("Condition number (log scale)")
    ax2.set_title("Conditioning context (ADR-0004: three DISTINCT matrices)")
    ax2.legend(fontsize=7.5, loc="upper left")
    ax2.grid(True, which="both", alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def fig_h2_flow_solves(out_path: Path = FIGURES_DIR / "h2_flow_solves.png") -> Path:
    """Flow-solve-count bar chart: monolithic vs nested LM, fair-paired by init strategy.

    Honest axis (linear, not truncated) -- the pre-registered >=100x claim FAILS
    against BOTH controls (STATS_PROTOCOL H2); this figure reports that faithfully
    rather than choosing an axis that flatters the ratio. Two matched pairs, grouped
    by shared initialization: presolve-init (monolithic baseline vs warm-started LM)
    and perturbed-init (monolithic init=perturbed vs cold-start LM) -- comparing
    across groups would mix the init-strategy factor into the H2 comparison, which
    STATS_PROTOCOL's fair-pairing requirement rules out.
    """
    mono_presolve = _load("t8_n08_baseline")
    mono_perturbed = _load("t8_init_perturbed")
    control_warm = _load("t8_n08_baseline_control")
    cold_path = RESULTS_DIR / "control_cold_control" / "result.json"

    groups = [
        (
            "presolve-init pair",
            "Monolithic\n(presolve)",
            mono_presolve["n_flow_solves_equivalent"],
            "Nested LM\n(warm-started)",
            control_warm["n_flow_solves_equivalent"],
        ),
    ]
    if cold_path.exists():
        with cold_path.open() as f:
            cold = json.load(f)
        groups.append(
            (
                "perturbed-init pair",
                "Monolithic\n(init=perturbed)",
                mono_perturbed["n_flow_solves_equivalent"],
                "Nested LM\n(cold-start)",
                cold["n_flow_solves_equivalent"],
            )
        )
    else:
        groups.append(
            (
                "perturbed-init pair",
                "Monolithic\n(init=perturbed)",
                mono_perturbed["n_flow_solves_equivalent"],
                "Nested LM\n(cold-start)\nPENDING",
                0,
            )
        )

    fig, ax = plt.subplots(figsize=(8.0, 5.0))
    x = 0
    xticks: list[float] = []
    xticklabels: list[str] = []
    max_val = max(v for _, _, mv, _, cv in groups for v in (mv, cv))
    for _group_label, mono_label, mono_val, nested_label, nested_val in groups:
        bar_mono = ax.bar(x, mono_val, color=C_BLUE, width=0.7)
        bar_nested = ax.bar(x + 0.9, nested_val, color=C_ORANGE, width=0.7)
        ax.text(x, mono_val + max_val * 0.02, f"{mono_val}", ha="center", va="bottom", fontsize=9)
        if nested_val > 0:
            ratio = nested_val / mono_val
            ax.text(
                x + 0.9,
                nested_val + max_val * 0.02,
                f"{nested_val}\n({ratio:.1f}x)",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        else:
            ax.text(x + 0.9, max_val * 0.02, "pending", ha="center", va="bottom", fontsize=9)
        xticks += [x, x + 0.9]
        xticklabels += [mono_label, nested_label]
        _ = (bar_mono, bar_nested)
        x += 2.4

    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels, fontsize=8)
    ax.set_ylabel("n_flow_solves_equivalent (linear axis, not truncated)")
    ax.set_title(
        "H2: flow-solve count, monolithic vs nested scipy.least_squares\n"
        "(fair-paired by shared init strategy; >=100x claim rejected under both pairs)"
    )
    threshold = mono_presolve["n_flow_solves_equivalent"] * 100
    ax.axhline(threshold, color="black", linestyle="--", linewidth=1.0)
    ax.text(
        -0.55,
        threshold * 1.01,
        "pre-registered >=100x threshold (vs presolve baseline)",
        fontsize=7,
    )
    ax.set_ylim(0, threshold * 1.08)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def fig_station_selection(out_path: Path = FIGURES_DIR / "station_selection.png") -> Path:
    """err_all_inf comparison: qr_pivot vs evenly-spaced station selection.

    The identifiability finding (docs/triz/T7-identifiability.md): both cells
    report converged=True from the Newton loop's internal stopping criterion, but
    evenly-spaced stations converge to the WRONG root (err_all_inf=1.4e-3, submap
    cond~3.5e12) while qr_pivot recovers the true coefficients to 3.15e-11 (submap
    cond~90). "Converged" (Newton residual small) and "correct" (recovers A*) are
    different claims -- this figure makes that gap visible.
    """
    cells = {
        "qr_pivot\n(station_selection)": "t8_n08_baseline",
        "even\n(evenly-spaced)": "t8_station_even",
    }
    labels = list(cells)
    errs = [_load(c)["err_all_inf"] for c in cells.values()]
    conds = [_load(c)["submap_cond"] for c in cells.values()]

    fig, ax = plt.subplots(figsize=(6.5, 5.2))
    bars = ax.bar(labels, errs, color=[C_BLUE, C_VERMILLION], width=0.5)
    ax.set_yscale("log")
    ax.set_ylim(top=max(errs) * 60)
    ax.axhline(
        1e-4, color="black", linestyle="--", linewidth=1.0, label="H1 gate (err_all_inf < 1e-4)"
    )
    for bar, err, cond in zip(bars, errs, conds, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            err * 1.3,
            f"{err:.2e}\nsubmap cond={cond:.2e}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.set_ylabel(r"$\|A-A^*\|_\infty$ (log scale)")
    ax.set_title(
        "Station selection is the identifiability guard\n(both cells report Newton-converged)"
    )
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(True, which="both", axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def generate_all() -> list[Path]:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return [
        fig_h3_convergence_overlay(),
        fig_n_sweep(),
        fig_h2_flow_solves(),
        fig_station_selection(),
    ]


if __name__ == "__main__":
    for path in generate_all():
        print(f"wrote {path}")
