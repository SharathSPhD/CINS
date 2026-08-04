"""Gate T4: analytic linear pre-solve — initialiser + realisability gate
(dossier §7.5). Thresholds read from configs/default.yaml
(``presolve.realisability_threshold``) per tests/CLAUDE.md.

Self-generated-target design (dossier §7.8's own recommendation, reused
here for T4): fit CST (n=8) to NACA 2412, use its own inviscid Cp as a
*guaranteed-realisable* target, and check the pre-solve recovers a
coefficient vector materially closer to the fitted A* than a perturbed
starting guess. A second case injects a target Cp no smooth CST-8 surface
can represent, and checks the realisability metric trips the gate.
"""

from __future__ import annotations

import numpy as np

from cins.config import load_config
from cins.cst.constraints import shared_le_radius_row
from cins.cst.fit import fit_cst
from cins.cst.geometry import cosine_spacing
from cins.solver.mfoil_adapter import make_mfoil
from cins.solver.presolve import (
    interpolate_cp_to_stations,
    presolve,
    solve_inviscid_cp,
)

CFG = load_config()
N_GATE = 8  # matches T2's "n=8 per side" gate
PSI = cosine_spacing(101)


def _fit_2412():
    m = make_mfoil(naca="2412", npanel=CFG.paneling.npanel)
    X = m.geom.xpoint
    return fit_cst(X[0], X[1], n=N_GATE, N1=CFG.cst.N1, N2=CFG.cst.N2, te_gap=CFG.cst.te_gap)


FIT = _fit_2412()
ZETA_T_U = CFG.cst.te_gap / 2.0
ZETA_T_L = -CFG.cst.te_gap / 2.0


def _stack(A_upper, A_lower):
    return np.concatenate([np.asarray(A_upper, dtype=float), np.asarray(A_lower, dtype=float)])


def test_presolve_initialiser_lands_closer_to_a_star_than_perturbed_start():
    """Self-generated realisable target: pre-solve from a 0.9x-scaled A*
    must land materially closer to A* than the starting guess did.

    Threshold justification: T4 is an *initialiser* for T5's Newton solve,
    not the inverse solve itself — it only needs to shrink the distance to
    the true answer enough to sit inside Newton's basin of attraction, not
    to reproduce it. A single linearized KKT step recovering >70% of the
    initial coefficient-space error (ratio < 0.3) is a strong initializer
    by that standard while leaving real room for T5 to do the rest of the
    (nonlinear) work; picking a much stricter number would implicitly turn
    this into a second inverse solve on a linearized model, defeating the
    point of keeping it cheap and linear.
    """
    a_star = FIT.A_upper, FIT.A_lower
    a_star_vec = _stack(*a_star)

    a0_upper = 0.9 * FIT.A_upper
    a0_lower = 0.9 * FIT.A_lower
    a0_vec = _stack(a0_upper, a0_lower)

    target_res = solve_inviscid_cp(FIT.A_upper, FIT.A_lower, ZETA_T_U, ZETA_T_L, PSI, CFG)
    baseline_res = solve_inviscid_cp(a0_upper, a0_lower, ZETA_T_U, ZETA_T_L, PSI, CFG)
    cp_target_at_a0_stations = interpolate_cp_to_stations(target_res, baseline_res)

    # shared_le_radius_row's default b=0 asserts *exact* upper/lower LE-radius
    # symmetry; the n=8 least-squares CST fit of a real airfoil satisfies
    # that only approximately (residual ~1e-2 here), so imposing the exact
    # b=0 would inject a target-inconsistent constraint into a test whose
    # whole point is a *guaranteed-realisable*, self-consistent target.
    # Use the fitted A*'s own actual value instead: the constraint's
    # structural row is identical (still "A_u0 + A_l0 = const"), only its
    # RHS is taken from the known-good answer rather than hardcoded to the
    # idealised value.
    g, _ = shared_le_radius_row(N_GATE, N_GATE)
    b = float(g @ a_star_vec)
    result = presolve(
        cp_target_at_a0_stations,
        a0_upper,
        a0_lower,
        ZETA_T_U,
        ZETA_T_L,
        PSI,
        [(g, b)],
        CFG,
    )

    err_before = float(np.linalg.norm(a0_vec - a_star_vec))
    err_after = float(np.linalg.norm(result.A - a_star_vec))
    ratio = err_after / err_before

    assert ratio < 0.3, (
        f"pre-solve did not land materially closer to A*: ratio={ratio:.4f} "
        f"(err_before={err_before:.4e}, err_after={err_after:.4e})"
    )
    assert result.realisability < CFG.presolve.realisability_threshold, (
        f"realisable self-generated target flagged infeasible: "
        f"realisability={result.realisability:.4f}"
    )
    assert result.realisable is True


def test_presolve_flags_unrealisable_spiky_target():
    """A localized, non-smooth Cp spike injected mid-chord is outside a
    smooth CST-8 surface's span; the realisability metric must trip."""
    a_star_vec = _stack(FIT.A_upper, FIT.A_lower)
    a0_upper = 0.9 * FIT.A_upper
    a0_lower = 0.9 * FIT.A_lower

    target_res = solve_inviscid_cp(FIT.A_upper, FIT.A_lower, ZETA_T_U, ZETA_T_L, PSI, CFG)
    baseline_res = solve_inviscid_cp(a0_upper, a0_lower, ZETA_T_U, ZETA_T_L, PSI, CFG)
    cp_target = interpolate_cp_to_stations(target_res, baseline_res)

    # Non-smooth wiggle: +0.8 to Cp over 3 adjacent mid-chord stations.
    spiky_target = cp_target.copy()
    mid = spiky_target.size // 2
    spiky_target[mid - 1 : mid + 2] += 0.8

    # Same target-consistent constraint RHS as the realisable-case test
    # (see its comment); an inconsistent b would trip the gate for the
    # wrong reason (constraint mismatch, not target non-smoothness).
    g, _ = shared_le_radius_row(N_GATE, N_GATE)
    b = float(g @ a_star_vec)
    result = presolve(
        spiky_target, a0_upper, a0_lower, ZETA_T_U, ZETA_T_L, PSI, [(g, b)], CFG
    )

    assert result.realisability > CFG.presolve.realisability_threshold, (
        f"spiky/unrepresentable target NOT flagged: "
        f"realisability={result.realisability:.4f} <= threshold "
        f"{CFG.presolve.realisability_threshold}"
    )
    assert result.realisable is False


def test_kkt_constraint_rows_satisfied_to_tight_tolerance():
    """G @ A == b at the pre-solve solution, to 1e-10 (dossier §7.5's KKT
    system enforces this exactly modulo linear-solve round-off)."""
    a_star_vec = _stack(FIT.A_upper, FIT.A_lower)
    a0_upper = 0.9 * FIT.A_upper
    a0_lower = 0.9 * FIT.A_lower

    target_res = solve_inviscid_cp(FIT.A_upper, FIT.A_lower, ZETA_T_U, ZETA_T_L, PSI, CFG)
    baseline_res = solve_inviscid_cp(a0_upper, a0_lower, ZETA_T_U, ZETA_T_L, PSI, CFG)
    cp_target = interpolate_cp_to_stations(target_res, baseline_res)

    g, _ = shared_le_radius_row(N_GATE, N_GATE)
    b = float(g @ a_star_vec)
    result = presolve(
        cp_target, a0_upper, a0_lower, ZETA_T_U, ZETA_T_L, PSI, [(g, b)], CFG
    )

    residual = float(g @ result.A - b)
    assert abs(residual) < 1e-10, f"constraint row not satisfied: G@A - b = {residual:.3e}"
    assert result.kkt_cond > 0 and np.isfinite(result.kkt_cond)
