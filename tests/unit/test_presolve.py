"""Unit tests for T4 pre-solve (dossier §7.5): M-column FD consistency, KKT
reduction to normal equations, and PresolveResult flag logic.

Thresholds/config from configs/default.yaml via cins.config.load_config()
(tests/CLAUDE.md).
"""

from __future__ import annotations

import numpy as np

from cins.config import load_config
from cins.cst.geometry import cosine_spacing
from cins.solver.presolve import (
    build_sensitivity_matrix,
    interpolate_cp_to_stations,
    presolve,
    solve_inviscid_cp,
)

CFG = load_config()


def _naca0012_A(n=4):
    """A small, cheap starting shape: symmetric-ish CST coefficients."""
    A_upper = np.full(n + 1, 0.17)
    A_lower = -np.full(n + 1, 0.17)
    return A_upper, A_lower


def test_m_column_matches_one_sided_forward_fd_sign_and_order():
    """Central-diff column k of M should agree in sign and rough magnitude
    with a one-sided forward FD at a smaller step (both estimate the same
    smooth derivative dCp/dA_k; they need not match exactly, but should not
    disagree in sign or by an order of magnitude for a smooth response)."""
    cfg = CFG.model_copy(deep=True)
    n = 4
    A_upper, A_lower = _naca0012_A(n)
    psi = cosine_spacing(41)
    zeta_T_u, zeta_T_l = 0.0, 0.0

    sens = build_sensitivity_matrix(A_upper, A_lower, zeta_T_u, zeta_T_l, psi, cfg)
    k = 0  # A_u0 -- leading-edge-radius coefficient, largest-effect column

    small_step = cfg.presolve.fd_step / 10.0
    au_base = solve_inviscid_cp(A_upper, A_lower, zeta_T_u, zeta_T_l, psi, cfg)
    au_p = A_upper.copy()
    au_p[k] += small_step
    res_p = solve_inviscid_cp(au_p, A_lower, zeta_T_u, zeta_T_l, psi, cfg)
    cp_p = interpolate_cp_to_stations(res_p, au_base)
    forward_fd_col = (cp_p - au_base.cp) / small_step

    central_col = sens.M[:, k]

    # Exclude the leading-edge stagnation region: the CST class function's
    # psi**N1 (N1=0.5) term has infinite slope at psi=0 (dossier §3.5,
    # FM-3; see also cins.cst.basis.le_modification's docstring), so
    # dCp/dA_0 there is genuinely near-singular and a central-diff at
    # fd_step legitimately disagrees with a forward-diff at fd_step/10 —
    # that is a real property of the CST/panel coupling, not an FD bug.
    # The comparison below targets the smooth interior response instead.
    le_region = au_base.x < 0.02
    # ignore stations where both are ~0 (flat far-field response)
    scale = np.maximum(np.abs(central_col), np.abs(forward_fd_col))
    mask = (scale > 1e-3) & ~le_region
    assert mask.sum() > 5, "expected a meaningfully large-response region"
    dot = np.dot(central_col[mask], forward_fd_col[mask])
    assert dot > 0, "central and forward FD estimates of dCp/dA_0 disagree in sign overall"

    ratio = np.linalg.norm(central_col[mask]) / np.linalg.norm(forward_fd_col[mask])
    assert 0.2 < ratio < 5.0, f"central vs forward FD magnitude ratio {ratio} implausible"


def test_kkt_reduces_to_normal_equations_with_empty_constraints():
    """With constraint_rows=[], the KKT block-solve must equal the plain
    least-squares normal-equations solve MtM @ delta_A = Mt @ delta_target."""
    cfg = CFG.model_copy(deep=True)
    n = 4
    A_upper, A_lower = _naca0012_A(n)
    psi = cosine_spacing(41)
    zeta_T_u, zeta_T_l = 0.0, 0.0

    sens = build_sensitivity_matrix(A_upper, A_lower, zeta_T_u, zeta_T_l, psi, cfg)
    # small synthetic target: baseline Cp nudged everywhere by a constant
    Cp_target = sens.Cp0 + 0.01

    result = presolve(
        Cp_target, A_upper, A_lower, zeta_T_u, zeta_T_l, psi, [], cfg
    )

    M = sens.M
    delta_target = Cp_target - sens.Cp0
    expected_delta_A = np.linalg.solve(M.T @ M, M.T @ delta_target)

    assert np.allclose(result.delta_A, expected_delta_A, rtol=1e-8, atol=1e-10)
    assert result.lam.shape == (0,)


def test_presolve_result_realisable_flag_matches_threshold():
    """realisable must be exactly (realisability <= cfg threshold), both when
    comfortably under and when deliberately pushed over via a spiky target."""
    cfg = CFG.model_copy(deep=True)
    n = 4
    A_upper, A_lower = _naca0012_A(n)
    psi = cosine_spacing(41)
    zeta_T_u, zeta_T_l = 0.0, 0.0

    sens = build_sensitivity_matrix(A_upper, A_lower, zeta_T_u, zeta_T_l, psi, cfg)

    # Case 1: target == baseline exactly -> realisability ~0, realisable True.
    result_easy = presolve(
        sens.Cp0, A_upper, A_lower, zeta_T_u, zeta_T_l, psi, [], cfg
    )
    assert result_easy.realisability <= cfg.presolve.realisability_threshold
    assert result_easy.realisable is True
    assert result_easy.realisable == (
        result_easy.realisability <= cfg.presolve.realisability_threshold
    )

    # Case 2: inject a large non-smooth spike CST cannot represent well.
    spiky_target = sens.Cp0.copy()
    mid = spiky_target.size // 2
    spiky_target[mid - 1 : mid + 2] += 5.0
    result_hard = presolve(
        spiky_target, A_upper, A_lower, zeta_T_u, zeta_T_l, psi, [], cfg
    )
    assert result_hard.realisability > cfg.presolve.realisability_threshold
    assert result_hard.realisable is False
    assert result_hard.realisable == (
        result_hard.realisability <= cfg.presolve.realisability_threshold
    )
