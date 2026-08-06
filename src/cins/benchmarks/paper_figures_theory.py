"""Paper P1 formulation figures: the CST basis, its derived engineering
parameters, the coupled viscous solution, and the leading-edge station
identifiability result. Regenerate via::

    .venv/bin/python -m cins.benchmarks.paper_figures_theory

Companion to ``cins.benchmarks.paper_figures``, which produces the evidence
figures from re-run inverse solves. Everything here is likewise computed, not
hand-drawn: the basis panels evaluate ``cins.cst.basis`` directly, the derived
parameters come from a real fit of NACA 2412, the viscous panels come from a
real coupled mfoil solve, and the identifiability panels come from real QR
station selections on a real sensitivity matrix.

Figures (written to ``experiments/results/t8/figures/paper/``):
    fig_cst_basis.png       -- class function, Bernstein shape functions, the
        weighted terms A_i C S_i, and their sum against the fitted surface.
        This is the figure the linearity argument of the Formulation section
        rests on: every panel but the first is linear in A.
    fig_cst_parameters.png  -- what the coefficients mean physically. LE
        radius from A_0, TE wedge angle from A_n, the superposition check
        that makes the geometric Jacobian block constant, and the derived
        parameters of the fitted section.
    fig_viscous_solution.png -- the coupled solve mfoil was chosen for:
        momentum and displacement thickness, skin friction, shape factor,
        edge velocity, and the displacement surface that closes the coupling.
    fig_le_identifiability.png -- target stations inside a prescribed-LE
        region carry almost no information about the free coefficients. Shows
        the sensitivity row norms collapsing over the prescribed region, the
        two QR station selections, and the resulting recovery.

Colorblind-safe (Okabe-Ito) palette, matching ``cins.benchmarks.figures``.
Matplotlib Agg backend only (headless-safe).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.linalg import qr as _qr  # noqa: E402

from cins.config import load_config  # noqa: E402
from cins.cst.basis import bernstein_matrix, class_fn  # noqa: E402
from cins.cst.fit import fit_cst  # noqa: E402
from cins.cst.geometry import coords_from_A, cosine_spacing  # noqa: E402
from cins.solver.mfoil_adapter import (  # noqa: E402
    make_mfoil,
    mfoil_module,
    refresh_post,
    release_transition,
    set_forced_transition,
)
from cins.solver.presolve import build_sensitivity_matrix  # noqa: E402

C_BLUE = "#0072B2"
C_ORANGE = "#E69F00"
C_GREEN = "#009E73"
C_VERMILLION = "#D55E00"
C_PURPLE = "#CC79A7"
C_SKY = "#56B4E9"
C_GRAY = "#666666"

FIGURES_DIR = Path("experiments/results/t8/figures/paper")
N_ORDER = 8  # order used for the illustrative fit; the app's CST Studio order

log = logging.getLogger(__name__)


def _naca2412_fit(n: int = N_ORDER):
    """A real fit of a real section. Nothing in these figures is invented."""
    X = make_mfoil(naca="2412").geom.xpoint
    return fit_cst(X[0], X[1], n)


# ------------------------------------------------------------------ fig (a)


def fig_cst_basis(out_dir: Path, n: int = N_ORDER) -> Path:
    """The parameterization, panel by panel, ending in the surface it builds.

    The point the Formulation section needs from this figure is that only the
    first panel is nonlinear in anything: the class function is fixed geometry
    (it does not depend on A at all), the shape functions are fixed
    polynomials, and the surface is their A-weighted sum. That is what makes
    the geometric Jacobian block constant and design-independent.
    """
    fit = _naca2412_fit(n)
    psi = np.linspace(0.0, 1.0, 400)
    C = class_fn(psi)
    S = bernstein_matrix(n, psi)  # (npts, n+1)
    A_u = np.asarray(fit.A_upper)

    fig, axes = plt.subplots(2, 2, figsize=(11.0, 7.4))

    ax = axes[0, 0]
    for n1, n2, style, lab in [
        (0.5, 1.0, "-", r"$N_1=0.5,\ N_2=1$ (round nose, sharp TE)"),
        (0.5, 0.5, "--", r"$N_1=N_2=0.5$ (ellipse)"),
        (1.0, 1.0, ":", r"$N_1=N_2=1$ (wedge)"),
    ]:
        ax.plot(psi, class_fn(psi, n1, n2), style, lw=2.0,
                color=C_BLUE if n1 == 0.5 and n2 == 1.0 else C_GRAY, label=lab)
    ax.set_title(r"(a) Class function $C(\psi)=\psi^{N_1}(1-\psi)^{N_2}$")
    ax.set_xlabel(r"$\psi = x/c$")
    ax.set_ylabel(r"$C(\psi)$")
    ax.legend(fontsize=7.5, loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[0, 1]
    for i in range(n + 1):
        ax.plot(psi, S[:, i], lw=1.6, alpha=0.9)
    ax.set_title(rf"(b) Bernstein shape functions $S_i(\psi)$, $n={n}$")
    ax.set_xlabel(r"$\psi = x/c$")
    ax.set_ylabel(r"$S_i(\psi)$")
    ax.text(0.5, 0.94, r"$S_i=\binom{n}{i}\psi^i(1-\psi)^{n-i}$",
            transform=ax.transAxes, ha="center", va="top", fontsize=9)
    ax.grid(alpha=0.3)

    ax = axes[1, 0]
    for i in range(n + 1):
        ax.plot(psi, A_u[i] * C * S[:, i], lw=1.5, alpha=0.9)
    ax.plot(psi, C * (S @ A_u), lw=2.6, color="k", label=r"$\sum_i A_i C S_i$")
    ax.set_title(r"(c) Weighted terms $A_i\,C(\psi)S_i(\psi)$ and their sum")
    ax.set_xlabel(r"$\psi = x/c$")
    ax.set_ylabel(r"$\zeta$ contribution")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[1, 1]
    coords = coords_from_A(
        fit.A_upper, fit.A_lower, fit.zeta_T_upper, fit.zeta_T_lower, cosine_spacing(200)
    )
    X = make_mfoil(naca="2412").geom.xpoint
    ax.plot(X[0], X[1], lw=3.2, color=C_GRAY, alpha=0.55, label="NACA 2412 (source)")
    ax.plot(coords[0], coords[1], lw=1.6, color=C_VERMILLION,
            label=rf"CST reconstruction, $n={n}$")
    ax.set_title("(d) The surface the coefficients describe")
    ax.set_xlabel(r"$x/c$")
    ax.set_ylabel(r"$z/c$")
    ax.axis("equal")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)
    ax.text(0.02, 0.04, f"fit RMS = {fit.rms:.2e} c", transform=ax.transAxes, fontsize=8.5)

    fig.tight_layout()
    out = out_dir / "fig_cst_basis.png"
    fig.savefig(out, dpi=190, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", out)
    return out


# ------------------------------------------------------------------ fig (b)


def fig_cst_parameters(out_dir: Path, n: int = N_ORDER) -> Path:
    """What the coefficients mean, and the superposition property.

    Panel (c) is the one that matters for the method: perturbing a single
    coefficient displaces the surface by exactly ``A_i C S_i`` regardless of
    where the other coefficients sit, so the geometric Jacobian block is
    assembled once and cached rather than rebuilt inside the Newton loop.
    """
    fit = _naca2412_fit(n)
    psi = cosine_spacing(240)
    A_u = np.asarray(fit.A_upper, dtype=float)
    A_l = np.asarray(fit.A_lower, dtype=float)

    fig, axes = plt.subplots(2, 2, figsize=(11.0, 7.4))

    # (a) LE radius is set by A_0 alone: R_LE = A_0^2 / 2
    ax = axes[0, 0]
    a0 = np.linspace(0.05, 0.35, 200)
    ax.plot(a0, a0**2 / 2.0, lw=2.2, color=C_BLUE)
    ax.axvline(A_u[0], color=C_VERMILLION, ls="--", lw=1.4)
    ax.plot([A_u[0]], [A_u[0] ** 2 / 2.0], "o", color=C_VERMILLION, ms=7,
            label=rf"fitted $A_{{u0}}={A_u[0]:.4f}$, $R_{{LE}}={A_u[0]**2/2:.5f}$")
    ax.set_title(r"(a) Leading-edge radius $R_{LE}=A_0^2/2$")
    ax.set_xlabel(r"$A_0$")
    ax.set_ylabel(r"$R_{LE}/c$")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.3)

    # (b) TE wedge half-angle from the last coefficient
    ax = axes[0, 1]
    beta_u = np.degrees(np.arctan(fit.zeta_T_upper - A_u[-1]))
    beta_l = np.degrees(np.arctan(-(fit.zeta_T_lower - A_l[-1])))
    an = np.linspace(0.0, 0.4, 200)
    ax.plot(an, np.degrees(np.arctan(fit.zeta_T_upper - an)), lw=2.2, color=C_BLUE,
            label="upper surface")
    ax.plot(an, np.degrees(np.arctan(-(fit.zeta_T_lower - (-an)))), lw=2.2,
            color=C_ORANGE, label="lower surface")
    ax.plot([A_u[-1]], [beta_u], "o", color=C_VERMILLION, ms=7)
    ax.set_title(r"(b) TE wedge half-angle $\zeta'(1)=\zeta_T-A_n$")
    ax.set_xlabel(r"$|A_n|$")
    ax.set_ylabel(r"half-angle (deg)")
    ax.text(0.03, 0.06,
            rf"fitted: upper ${beta_u:.2f}^\circ$, lower ${beta_l:.2f}^\circ$",
            transform=ax.transAxes, fontsize=8.5)
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)

    # (c) superposition, measured rather than asserted. The analytic
    # prediction delta*C*S_i is drawn as a line; the markers are the actual
    # surface displacement obtained by perturbing that one coefficient of the
    # fitted section and re-evaluating the geometry. They coincide to machine
    # precision, which is the property the cached Jacobian block relies on.
    ax = axes[1, 0]
    C = class_fn(psi)
    S = bernstein_matrix(n, psi)
    delta = 0.02
    base_u = coords_from_A(
        A_u, A_l, fit.zeta_T_upper, fit.zeta_T_lower, psi
    )[1][-psi.size :]
    worst = 0.0
    for i, col in zip((1, 3, 6), (C_BLUE, C_GREEN, C_PURPLE)):
        pert = A_u.copy()
        pert[i] += delta
        moved_u = coords_from_A(
            pert, A_l, fit.zeta_T_upper, fit.zeta_T_lower, psi
        )[1][-psi.size :]
        measured = moved_u - base_u
        predicted = delta * C * S[:, i]
        worst = max(worst, float(np.max(np.abs(measured - predicted))))
        ax.plot(psi, predicted, lw=2.2, color=col, alpha=0.9,
                label=rf"$\delta A_{{u{i}}}\,C S_{{{i}}}$ (analytic)")
        ax.plot(psi[::12], measured[::12], "o", ms=3.6, color=col, mfc="none")
    ax.set_title(rf"(c) Surface displacement per coefficient ($\delta A={delta}$)")
    ax.set_xlabel(r"$\psi = x/c$")
    ax.set_ylabel(r"$\delta\zeta$")
    ax.text(0.5, 0.96,
            "markers: measured displacement; lines: analytic\n"
            rf"max deviation {worst:.1e}, independent of the other coefficients",
            transform=ax.transAxes, ha="center", va="top", fontsize=8.0)
    ax.legend(fontsize=7.5, loc="lower right")
    ax.grid(alpha=0.3)

    # (d) the coefficient vector itself
    ax = axes[1, 1]
    idx = np.arange(n + 1)
    w = 0.38
    ax.bar(idx - w / 2, A_u, w, color=C_BLUE, label=r"$A_{u,i}$ (upper)")
    ax.bar(idx + w / 2, A_l, w, color=C_ORANGE, label=r"$A_{l,i}$ (lower)")
    ax.axhline(0.0, color="k", lw=0.8)
    ax.set_title("(d) Fitted coefficient vector, NACA 2412")
    ax.set_xlabel("coefficient index $i$")
    ax.set_ylabel(r"$A_i$")
    ax.set_xticks(idx)
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=0.3, axis="y")

    fig.tight_layout()
    out = out_dir / "fig_cst_parameters.png"
    fig.savefig(out, dpi=190, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", out)
    return out


# ------------------------------------------------------------------ fig (c)


def fig_viscous_solution(out_dir: Path, naca: str = "2412", alpha: float = 2.0) -> Path:
    """The coupled viscous solution, which is the reason mfoil was chosen.

    The inverse system is appended to mfoil's *viscous* global system, so the
    boundary layer is inside the Newton solve rather than a post-process. This
    figure shows the state variables that carries: momentum and displacement
    thickness, skin friction, shape factor, the edge velocity the inviscid
    half sees, and the displacement surface that closes the coupling.
    """
    cfg = load_config()
    mod = mfoil_module()
    m = make_mfoil(naca=naca)
    m.setoper(alpha=alpha, Re=cfg.operating.Re)
    m.solve()
    if not m.glob.conv:
        raise RuntimeError("viscous baseline solve did not converge")
    set_forced_transition(m, cfg.transition.xtr_upper, cfg.transition.xtr_lower)
    try:
        mod.solve_coupled(m)
        refresh_post(m)
        if not m.glob.conv:
            raise RuntimeError("tripped coupled solve did not converge")
        x = np.asarray(m.foil.x[0])
        z = np.asarray(m.foil.x[1])
        N = m.foil.N
        th = np.asarray(m.post.th)[:N]
        ds = np.asarray(m.post.ds)[:N]
        cf = np.asarray(m.post.cf)[:N]
        Hk = np.asarray(m.post.Hk)[:N]
        ue = np.asarray(m.post.ue)[:N]
        cl, cd = float(m.post.cl), float(m.post.cd)
        xtr_u = float(cfg.transition.xtr_upper)
        xtr_l = float(cfg.transition.xtr_lower)
    finally:
        release_transition()

    le = int(np.argmin(x))
    # mfoil node order runs TE lower -> LE -> TE upper
    sl = slice(0, le + 1)
    su = slice(le, N)

    def _asc(a, b):
        aa, bb = np.asarray(a), np.asarray(b)
        return (aa[::-1], bb[::-1]) if aa.size > 1 and aa[0] > aa[-1] else (aa, bb)

    fig, axes = plt.subplots(2, 3, figsize=(13.6, 7.2))

    panels = [
        (axes[0, 0], th, r"momentum thickness $\theta/c$", "(a)"),
        (axes[0, 1], ds, r"displacement thickness $\delta^*/c$", "(b)"),
        (axes[0, 2], cf, r"skin friction $c_f$", "(c)"),
        (axes[1, 0], Hk, r"kinematic shape factor $H_k$", "(d)"),
        (axes[1, 1], ue, r"edge velocity $u_e/V_\infty$", "(e)"),
    ]
    for ax, q, lab, tag in panels:
        xu, qu = _asc(x[su], q[su])
        xl, ql = _asc(x[sl], q[sl])
        ax.plot(xu, qu, lw=1.9, color=C_BLUE, label="upper")
        ax.plot(xl, ql, lw=1.9, color=C_ORANGE, label="lower")
        ax.axvline(xtr_u, color=C_BLUE, ls=":", lw=1.2)
        ax.axvline(xtr_l, color=C_ORANGE, ls=":", lw=1.2)
        ax.set_title(f"{tag} {lab}", fontsize=10)
        ax.set_xlabel(r"$x/c$")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7.5)

    ax = axes[1, 2]
    xu, zu = _asc(x[su], z[su])
    _, du = _asc(x[su], ds[su])
    xl, zl = _asc(x[sl], z[sl])
    _, dl = _asc(x[sl], ds[sl])
    ax.plot(xu, zu, lw=1.6, color="k")
    ax.plot(xl, zl, lw=1.6, color="k", label="airfoil surface")
    ax.plot(xu, zu + du, lw=1.7, color=C_BLUE, ls="--", label=r"$+\delta^*$ upper")
    ax.plot(xl, zl - dl, lw=1.7, color=C_ORANGE, ls="--", label=r"$-\delta^*$ lower")
    ax.fill_between(xu, zu, zu + du, color=C_BLUE, alpha=0.18)
    ax.fill_between(xl, zl - dl, zl, color=C_ORANGE, alpha=0.18)
    ax.set_title("(f) displacement surface: the coupling term", fontsize=10)
    ax.set_xlabel(r"$x/c$")
    ax.set_ylabel(r"$z/c$")
    ax.axis("equal")
    ax.legend(fontsize=7.5, loc="lower right")
    ax.grid(alpha=0.3)

    fig.suptitle(
        rf"NACA {naca}, $\alpha={alpha:.1f}^\circ$, $Re={cfg.operating.Re:.2e}$, "
        rf"transition forced at $x/c$ = {xtr_u:.2f} upper / {xtr_l:.2f} lower; "
        rf"$c_l={cl:.4f}$, $c_d={cd:.5f}$",
        fontsize=10.5,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    out = out_dir / "fig_viscous_solution.png"
    fig.savefig(out, dpi=185, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", out)
    return out


# ------------------------------------------------------------------ fig (d)


def fig_le_identifiability(out_dir: Path, n: int = 6) -> Path:
    """Why target stations must be kept out of a prescribed leading edge.

    When the leading edge is prescribed, ``A_u0`` and ``A_l0`` are given
    rather than solved. A target row placed inside that region then constrains
    pressure over a piece of surface that cannot move, so it contributes
    almost nothing about the free coefficients: the square system stays
    formally full-rank while becoming numerically near-dependent, and
    converges to a root that is not the generating geometry.
    """
    cfg = load_config()
    fit = _naca2412_fit(n)
    psi = cosine_spacing(160)
    # Evaluate at the SAME perturbed starting geometry the archived run used,
    # so the conditioning shown here is the conditioning that run reports
    # rather than a different one computed at the fitted section.
    a_star = np.concatenate([fit.A_upper, fit.A_lower])
    rng = np.random.default_rng(42)
    a0 = a_star + 0.004 * rng.standard_normal(a_star.size)
    n_u = n_l = n
    n_a = n_u + n_l + 2
    le_frac = float(cfg.cst.prescribed_le_fraction)

    sens = build_sensitivity_matrix(
        a0[: n_u + 1], a0[n_u + 1 :], fit.zeta_T_upper, fit.zeta_T_lower, psi, cfg
    )
    xs = np.asarray(sens.x_stations)
    free_idx = np.array([i for i in range(n_a) if i not in (0, n_u + 1)])
    M_free = sens.M[:, free_idx]
    row_norm = np.linalg.norm(M_free, axis=1)

    # the two selections that separate the configurations
    n_pick = len(free_idx)  # alpha fixed, no constraint rows: matches the run
    _, _, piv_all = _qr(M_free.T, pivoting=True)
    st_all = np.sort(piv_all[:n_pick])
    cand = np.nonzero(xs >= le_frac)[0]
    _, _, piv_f = _qr(sens.M[cand][:, free_idx].T, pivoting=True)
    st_filt = np.sort(cand[piv_f[:n_pick]])

    cond_all = float(np.linalg.cond(sens.M[st_all][:, free_idx]))
    cond_filt = float(np.linalg.cond(sens.M[st_filt][:, free_idx]))

    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.3))

    ax = axes[0]
    ax.semilogy(xs, np.maximum(row_norm, 1e-16), lw=1.5, color=C_BLUE)
    ax.axvspan(0.0, le_frac, color=C_VERMILLION, alpha=0.16)
    ax.text(le_frac / 2, 0.97, "prescribed\nLE region", transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=8, color=C_VERMILLION)
    ax.set_title("(a) Sensitivity of $C_p$ to the free coefficients", fontsize=10)
    ax.set_xlabel(r"station $x/c$")
    ax.set_ylabel(r"$\|\partial C_p/\partial A_{\mathrm{free}}\|_2$")
    ax.grid(alpha=0.3, which="both")

    ax = axes[1]
    ax.plot(xs[st_all], np.full(st_all.size, 1.0), "o", color=C_VERMILLION, ms=7,
            label=f"unrestricted QR (cond {cond_all:.3g})")
    ax.plot(xs[st_filt], np.full(st_filt.size, 0.0), "o", color=C_GREEN, ms=7,
            label=f"restricted to $x\\geq{le_frac}$ (cond {cond_filt:.3g})")
    ax.axvspan(0.0, le_frac, color=C_VERMILLION, alpha=0.16)
    ax.set_ylim(-0.6, 1.6)
    ax.set_yticks([0.0, 1.0])
    ax.set_yticklabels(["restricted", "unrestricted"], fontsize=8)
    ax.set_title("(b) Selected target stations", fontsize=10)
    ax.set_xlabel(r"station $x/c$")
    ax.legend(fontsize=7.5, loc="upper center")
    ax.grid(alpha=0.3, axis="x")

    ax = axes[2]
    # Read the comparison from the archived run rather than restating it here.
    # These numbers were previously hardcoded, which meant the figure could not
    # go stale in step with the experiment and did not satisfy the project's
    # own rule that every reported number trace to a manifest.
    res_path = Path("experiments/results/le_stations/result.json")
    if not res_path.exists():
        raise FileNotFoundError(
            f"{res_path} not found; run experiments/run_le_stations.py first"
        )
    cells = json.loads(res_path.read_text())["cells"]
    cu, cr = cells["unrestricted"], cells["restricted"]
    labels = ["submap\ncond", "Newton\niterations", r"$\|A-A^*\|_\infty$",
              "surface\noffset (mc)"]
    unrestricted = [cu["submap_cond"], float(cu["iterations"]),
                    cu["err_free_inf"], cu["max_surface_offset_mc"]]
    restricted = [cr["submap_cond"], float(cr["iterations"]),
                  cr["err_free_inf"], cr["max_surface_offset_mc"]]
    xpos = np.arange(len(labels))
    w = 0.36
    norm_u = [1.0] * len(labels)
    norm_r = [restricted[i] / unrestricted[i] for i in range(len(labels))]
    ax.bar(xpos - w / 2, norm_u, w, color=C_VERMILLION, label="LE stations included")
    ax.bar(xpos + w / 2, norm_r, w, color=C_GREEN, label="LE stations excluded")
    ax.set_yscale("log")
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("relative to unrestricted")
    ax.set_title("(c) Effect on the raw-target solve", fontsize=10)
    ax.legend(fontsize=7.5)
    ax.grid(alpha=0.3, axis="y", which="both")
    for i, v in enumerate(norm_r):
        ax.text(i + w / 2, v * 1.25, f"{v:.3g}x", ha="center", fontsize=7.5)

    fig.tight_layout()
    out = out_dir / "fig_le_identifiability.png"
    fig.savefig(out, dpi=190, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", out)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out_dir = FIGURES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_cst_basis(out_dir)
    fig_cst_parameters(out_dir)
    fig_viscous_solution(out_dir)
    fig_le_identifiability(out_dir)
    print("theory figures written to", out_dir)


if __name__ == "__main__":
    main()
