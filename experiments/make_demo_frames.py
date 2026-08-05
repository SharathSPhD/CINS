"""Render animation frames of a live monolithic inverse solve.

Runs the T7 self-consistency pipeline with a diagnostics recorder that captures
the geometry, the pressure distribution at the target stations and the residual
norms at every Newton iteration, then renders those stages as video frames.

The output is the centrepiece of the project demo video: the airfoil visibly
converging onto the target while the sampled pressures collapse onto the target
values and the residual falls quadratically.

Run:  .venv/bin/python experiments/make_demo_frames.py [out_dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

from cins.benchmarks.instrumentation import EvalCounters, instrument_evaluations
from cins.benchmarks.pipeline import prepare_cell
from cins.config import load_config
from cins.cst.geometry import coords_from_A
from cins.diagnostics.recorder import NewtonDiagnostics
from cins.solver.mfoil_adapter import mfoil_module, release_transition
from cins.solver.newton import InverseProblem, solve_inverse

BG = "#0b1017"
FG = "#e8eef4"
MUTED = "#7d8fa1"
ACCENT = "#38bdf8"
TARGET = "#f59e0b"
GOOD = "#34d399"
GRID = "#1e2b39"

HOLD_FIRST = 18   # frames held on the starting shape
TWEEN = 14        # interpolated frames between Newton iterations
HOLD_LAST = 40    # frames held on the converged result


class StageCapture(NewtonDiagnostics):
    """Records geometry and pressure state at each Newton iteration."""

    def __init__(self, m, prep, cfg):
        super().__init__(config=cfg)
        self._m = m
        self._prep = prep
        self.stages: list[dict] = []

    def record_iteration(self, it: int, **kw):  # type: ignore[override]
        rec = super().record_iteration(it, **kw)
        mod = mfoil_module()
        cp_all, _ = mod.get_cp(self._m.glob.U[3], self._m.param)
        st = np.asarray(self._prep.stations)
        self.stages.append(
            {
                "it": int(it),
                "x": np.asarray(self._m.foil.x[0]).tolist(),
                "y": np.asarray(self._m.foil.x[1]).tolist(),
                "cp_x": np.asarray(self._m.foil.x[0])[st].tolist(),
                "cp": np.asarray(cp_all)[st].tolist(),
                "R": float(kw.get("R_norm") or 0.0),
                "T": float(kw.get("T_norm") or 0.0),
                "G": float(kw.get("G_norm") or 0.0),
            }
        )
        return rec


def run_capture(out_dir: Path) -> dict:
    cfg = load_config()
    counters = EvalCounters()
    with instrument_evaluations(counters):
        prep = prepare_cell(cfg, counters, cell_name="demo", config_path=None, t0=0.0)
        assert prep.early_failure is None, prep.early_failure
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
        diag = StageCapture(prep.m, prep, cfg)
        res = solve_inverse(prep.m, prob, cfg, diag=diag)
    release_transition()

    target = coords_from_A(
        prep.fit.A_upper, prep.fit.A_lower,
        prep.fit.zeta_T_upper, prep.fit.zeta_T_lower, prep.psi,
    )
    a_star = np.concatenate([prep.fit.A_upper, prep.fit.A_lower])
    a_fin = np.concatenate([res.A_upper, res.A_lower])
    payload = {
        "stages": diag.stages,
        "target_x": target[0].tolist(),
        "target_y": target[1].tolist(),
        "cp_target": np.asarray(prep.cp_target).tolist(),
        "cp_target_x": np.asarray(prep.m.foil.x[0])[prep.stations].tolist(),
        "converged": bool(res.converged),
        "iterations": int(res.iterations),
        "err_free_inf": float(np.max(np.abs(a_fin[prep.free_idx] - a_star[prep.free_idx]))),
        "residual_history": [float(r) for r in res.residual_norms],
    }
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


def render(payload: dict, out_dir: Path, width=1920, height=1080, dpi=120) -> int:
    stages = payload["stages"]
    tx, ty = np.array(payload["target_x"]), np.array(payload["target_y"])
    cpt_x = np.array(payload["cp_target_x"])
    cpt = np.array(payload["cp_target"])
    hist = payload["residual_history"]

    frames_dir = out_dir / "frames"
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

    for k, (i, frac) in enumerate(seq):
        a = stages[i]
        b = stages[min(i + 1, len(stages) - 1)]
        gx = np.array(a["x"]) * (1 - frac) + np.array(b["x"]) * frac
        gy = np.array(a["y"]) * (1 - frac) + np.array(b["y"]) * frac
        cp = np.array(a["cp"]) * (1 - frac) + np.array(b["cp"]) * frac

        fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=BG)
        gs = GridSpec(2, 2, figure=fig, height_ratios=[1.15, 1.0],
                      hspace=0.32, wspace=0.18,
                      left=0.06, right=0.97, top=0.86, bottom=0.09)

        fig.text(0.06, 0.945, "Monolithic CST-Newton inverse solve",
                 color=FG, fontsize=21, fontweight="bold")
        fig.text(0.06, 0.905,
                 "Target pressure distribution in, airfoil geometry out. "
                 "No optimizer, no surrogate.", color=MUTED, fontsize=12)
        fig.text(0.97, 0.945, f"Newton iteration {a['it']}",
                 color=ACCENT, fontsize=15, ha="right", family="monospace")

        ax1 = fig.add_subplot(gs[0, :])
        _style(ax1, "Geometry: current shape against the target")
        ax1.plot(tx, ty, color=TARGET, lw=3.0, alpha=0.5, label="target", zorder=2)
        ax1.plot(gx, gy, color=ACCENT, lw=2.0, label="current", zorder=3)
        ax1.set_xlim(-0.03, 1.03)
        ax1.set_ylim(-0.16, 0.19)
        ax1.set_aspect("equal", adjustable="box")
        ax1.set_xlabel("x / c", color=MUTED, fontsize=10)
        leg = ax1.legend(loc="upper right", frameon=False, fontsize=10)
        for t in leg.get_texts():
            t.set_color(FG)

        ax2 = fig.add_subplot(gs[1, 0])
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
        leg2 = ax2.legend(loc="lower right", frameon=False, fontsize=9)
        for t in leg2.get_texts():
            t.set_color(FG)

        ax3 = fig.add_subplot(gs[1, 1])
        _style(ax3, "Residual norm per iteration")
        shown = hist[: a["it"] + 1] if a["it"] + 1 <= len(hist) else hist
        ax3.semilogy(range(len(shown)), shown, color=GOOD, lw=2.2,
                     marker="o", markersize=6)
        ax3.set_xlim(-0.3, max(len(hist) - 0.7, 1))
        ax3.set_ylim(min(hist) * 0.25, max(hist) * 4)
        ax3.set_xlabel("Newton iteration", color=MUTED, fontsize=10)
        ax3.set_ylabel(r"$\|R\|$", color=MUTED, fontsize=10)
        if shown:
            ax3.annotate(f"{shown[-1]:.2e}",
                         xy=(len(shown) - 1, shown[-1]),
                         xytext=(-14, 16), textcoords="offset points",
                         color=GOOD, fontsize=11, family="monospace")

        if k >= len(seq) - HOLD_LAST:
            fig.text(0.5, 0.028,
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
    print(f"captured {len(payload['stages'])} stages, rendered {n} frames -> {out_dir/'frames'}")
    print(f"converged={payload['converged']} iters={payload['iterations']} "
          f"err={payload['err_free_inf']:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
