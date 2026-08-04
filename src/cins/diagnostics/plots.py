"""T6 diagnostics figure builders (dossier §7.7, SPEC.md §6).

Each ``fig_*`` function takes a :class:`cins.diagnostics.recorder.DiagnosticsReport`
and returns a ``matplotlib.figure.Figure``. No ``plt.show()`` is ever called; saving
(``fig.savefig(...)``) is the caller's responsibility (tests/CLAUDE.md: no test may
depend on matplotlib rendering).

Backend is forced to ``Agg`` at import time so these builders work headless in CI
and in test runs with no display.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from cins.diagnostics.recorder import DiagnosticsReport  # noqa: E402

_LE_REGION_DEFAULT = 0.05  # x/c fraction marked as "nose"
# (matches cst.prescribed_le_fraction default)


def _new_figure(figsize: tuple[float, float] = (6.0, 4.0)) -> tuple[Figure, plt.Axes]:
    """Single helper for consistent, minimal figure styling across D-1..D-6."""
    fig, ax = plt.subplots(figsize=figsize)
    ax.grid(True, alpha=0.3, linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig, ax


def fig_d1_residuals(report: DiagnosticsReport) -> Figure:
    """D-1: per-block residual norms (‖R‖, ‖T‖, ‖G‖) vs iteration, semilogy."""
    fig, ax = _new_figure()
    its = [r.it for r in report.iterations]
    series = (
        ("‖R‖ (flow)", "R_norm"),
        ("‖T‖ (Cp target)", "T_norm"),
        ("‖G‖ (constraints)", "G_norm"),
    )
    for label, attr in series:
        vals = [getattr(r, attr) for r in report.iterations]
        ax.semilogy(its, np.maximum(vals, 1e-300), marker="o", markersize=3, label=label)
    ax.set_xlabel("Newton iteration")
    ax.set_ylabel("residual norm")
    ax.set_title("D-1: per-block residual norms")
    ax.legend(frameon=False)
    fig.tight_layout()
    return fig


def fig_d4_row_norm_profile(
    report: DiagnosticsReport, le_region: float = _LE_REGION_DEFAULT
) -> Figure:
    """D-4: row-norm profile of ∂R/∂A vs chordwise station (expect a nose spike).

    Uses the last iteration record that carries both ``dR_dA_row_norms`` and
    ``x_stations``. The leading-edge region (``x/c <= le_region``) is shaded to
    make the expected FM-3 spike easy to spot.
    """
    fig, ax = _new_figure()
    record = next(
        (
            r
            for r in reversed(report.iterations)
            if r.dR_dA_row_norms is not None and r.x_stations is not None
        ),
        None,
    )
    if record is None:
        ax.set_title("D-4: row-norm profile (no data recorded)")
        ax.set_xlabel("x/c")
        ax.set_ylabel("‖∂R/∂A row‖")
        fig.tight_layout()
        return fig

    x = np.asarray(record.x_stations)
    y = np.asarray(record.dR_dA_row_norms)
    order = np.argsort(x)
    ax.plot(x[order], y[order], marker=".", markersize=3, linewidth=1.0, color="tab:blue")
    le_x1 = x.min() + le_region * (x.max() - x.min())
    ax.axvspan(x.min(), le_x1, color="tab:red", alpha=0.12, label="LE region")
    ax.set_xlabel("x/c")
    ax.set_ylabel("‖∂R/∂A row‖")
    ax.set_title(f"D-4: row-norm profile (iteration {record.it})")
    ax.legend(frameon=False)
    fig.tight_layout()
    return fig


def fig_d5_transition_history(report: DiagnosticsReport) -> Figure:
    """D-5: transition-location history per iteration (FM-4 chatter detector)."""
    fig, ax = _new_figure()
    its, xt = [], []
    for r in report.iterations:
        if r.transition_xt is not None:
            its.append(r.it)
            xt.append(r.transition_xt)

    if its and isinstance(xt[0], (list, tuple)) and len(xt[0]) >= 2:
        xt_arr = np.asarray(xt, dtype=float)
        ax.plot(its, xt_arr[:, 0], marker="o", markersize=3, label="upper")
        ax.plot(its, xt_arr[:, 1], marker="o", markersize=3, label="lower")
        ax.legend(frameon=False)
    else:
        ax.plot(its, xt, marker="o", markersize=3, color="tab:green")

    ax.set_xlabel("Newton iteration")
    ax.set_ylabel("transition location x_t/c")
    ax.set_title("D-5: transition-location history")
    fig.tight_layout()
    return fig


def fig_d6_convergence(report: DiagnosticsReport) -> Figure:
    """D-6: Newton convergence history (log‖R‖ vs iteration) with a quadratic
    reference slope anchored at the second-to-last point, using
    ``report.convergence_order`` (falls back to 2.0 if unavailable)."""
    fig, ax = _new_figure()
    its = [r.it for r in report.iterations]
    r_norms = np.asarray([r.R_norm for r in report.iterations])
    ax.semilogy(its, np.maximum(r_norms, 1e-300), marker="o", markersize=3, label="‖R‖")

    if len(its) >= 2:
        p = report.convergence_order if report.convergence_order is not None else 2.0
        # Reference line in log-space with slope p (per iteration step), anchored
        # so it passes through the final residual, for visual comparison against
        # the quadratic (p=2) tail the architectural claim predicts.
        n_back = min(4, len(its))
        xs = np.asarray(its[-n_back:], dtype=float)
        ref_log = np.log10(max(r_norms[-1], 1e-300)) + p * (xs - xs[-1]) / max(xs[-1] - xs[0], 1)
        ax.semilogy(xs, 10.0**ref_log, "--", color="gray", label=f"order-{p:.2f} reference")

    ax.set_xlabel("Newton iteration")
    ax.set_ylabel("‖R‖")
    title = "D-6: Newton convergence history"
    if report.convergence_order is not None:
        title += f" (est. order p={report.convergence_order:.2f})"
    ax.set_title(title)
    ax.legend(frameon=False)
    fig.tight_layout()
    return fig
