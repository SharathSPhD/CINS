"""Gate T2: CST fit quality (dossier §7.3).

'Fit CST to NACA 2412 ... Target RMS < 0.1% chord. Record cond(GtG) versus n
— this is the empirical FM-2 curve.'

Thresholds are read from configs/default.yaml via cins.config.load_config()
(tests/CLAUDE.md: tests and runtime share one source of truth). This test
also archives the FM-2 conditioning-vs-n evidence to
experiments/results/t2_gram_conditioning.json for the paper.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import numpy as np
import pytest

from cins.config import REPO_ROOT, load_config
from cins.cst.basis import surface
from cins.cst.fit import fit_cst
from cins.solver.mfoil_adapter import make_mfoil
from tests._naca5 import naca5_points

CFG = load_config()
N_GATE = 8  # "n=8 per side" per dossier §7.3
N_SWEEP = [4, 6, 8, 10, 12, 16]
RESULTS_PATH = REPO_ROOT / CFG.experiment.results_dir / "t2_gram_conditioning.json"


def _airfoil_coords(name: str) -> np.ndarray:
    """(2, N) coordinate array for each gate airfoil.

    NACA 2412, 0012, 4415 come straight from mfoil (make_mfoil(naca=...)).
    NACA 23012 cannot: vendor/mfoil/mfoil.py's 5-digit branch of
    naca_points() calls Python lists as functions (``mv(n)`` instead of
    ``mv[int(n)-1]``) and raises TypeError unconditionally — a real vendor
    bug, out of scope for T2 (flagged separately). tests/_naca5.py
    reimplements the same (corrected) formula so the gate can still cover
    the 5-digit case the dossier asks for.
    """
    if name == "23012":
        return naca5_points(name, npoint_per_side=100)
    m = make_mfoil(naca=name, npanel=199)
    return m.geom.xpoint


AIRFOILS = ["2412", "0012", "23012", "4415"]


@pytest.mark.parametrize("naca", AIRFOILS)
def test_t2_fit_rms_below_gate(naca):
    X = _airfoil_coords(naca)
    result = fit_cst(X[0], X[1], n=N_GATE, N1=CFG.cst.N1, N2=CFG.cst.N2)
    assert result.rms < CFG.gates.t2_fit_rms_max, (
        f"NACA {naca}: rms={result.rms:.3e} >= gate {CFG.gates.t2_fit_rms_max:.3e}"
    )


@pytest.mark.parametrize("naca", AIRFOILS)
def test_t2_round_trip_reproduces_fit_rms(naca):
    """surface() from the fitted A must reproduce the original data within
    the reported RMS (not just "close" — checked against the same residual
    definition fit_cst uses internally)."""
    X = _airfoil_coords(naca)
    result = fit_cst(X[0], X[1], n=N_GATE, N1=CFG.cst.N1, N2=CFG.cst.N2)

    x0 = X[0, :].min()
    chord = X[0, :].max() - x0
    le_idx = int(np.argmin(X[0, :]))

    psi_lower = (X[0, : le_idx + 1][::-1] - x0) / chord
    zeta_lower = X[1, : le_idx + 1][::-1] / chord
    psi_upper = (X[0, le_idx:] - x0) / chord
    zeta_upper = X[1, le_idx:] / chord

    # _airfoil_coords may hand back either surface first; use fit_cst's own
    # convention (mean-zeta-higher = upper) to pick the right pairing.
    if np.mean(zeta_lower) > np.mean(zeta_upper):
        psi_lower, zeta_lower, psi_upper, zeta_upper = (
            psi_upper,
            zeta_upper,
            psi_lower,
            zeta_lower,
        )

    z_upper_fit = surface(
        psi_upper, result.A_upper, result.zeta_T_upper, CFG.cst.N1, CFG.cst.N2
    )
    z_lower_fit = surface(
        psi_lower, result.A_lower, result.zeta_T_lower, CFG.cst.N1, CFG.cst.N2
    )
    resid = np.concatenate([z_upper_fit - zeta_upper, z_lower_fit - zeta_lower])
    rms_round_trip = float(np.sqrt(np.mean(resid**2)))
    assert rms_round_trip == pytest.approx(result.rms, abs=1e-9)


def test_t2_gram_conditioning_curve_archived():
    """FM-2 evidence (dossier §4 FM-2, §7.3): cond(GtG) vs n, per airfoil.

    Not itself a pass/fail gate on a numeric threshold (FM-2 is a *known*
    growth trend, not a target) — it archives the measured curve with a
    reproducibility manifest so the paper can cite it.
    """
    records = []
    for naca in AIRFOILS:
        X = _airfoil_coords(naca)
        for n in N_SWEEP:
            result = fit_cst(X[0], X[1], n=n, N1=CFG.cst.N1, N2=CFG.cst.N2)
            records.append(
                {
                    "airfoil": naca,
                    "n": n,
                    "cond": result.gram_condition,
                    "rms": result.rms,
                }
            )

    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        git_sha = "unknown"

    manifest = {
        "git_sha": git_sha,
        "config_hash": CFG.config_hash(),
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "n_gate": N_GATE,
        "n_sweep": N_SWEEP,
        "airfoils": AIRFOILS,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps({"manifest": manifest, "records": records}, indent=2)
    )

    assert RESULTS_PATH.exists()
    # sanity: conditioning should grow (not strictly monotone per airfoil,
    # but the largest-n case must be worse than the smallest-n case) —
    # the qualitative FM-2 signature the dossier predicts.
    for naca in AIRFOILS:
        rows = [r for r in records if r["airfoil"] == naca]
        cond_lo = next(r["cond"] for r in rows if r["n"] == N_SWEEP[0])
        cond_hi = next(r["cond"] for r in rows if r["n"] == N_SWEEP[-1])
        assert cond_hi > cond_lo, f"{naca}: expected cond(GtG) to grow with n"
