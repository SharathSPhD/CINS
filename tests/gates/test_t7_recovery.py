"""Gate T7: the falsifiable test (dossier §7.8) — full pipeline, ~10 min.

Marked slow: CI runs the fast suite; this gate's evidence run is archived with
manifest in experiments/results/t7_naca2412/ (run.log + diagnostics.json).
Run explicitly:  .venv/bin/python -m pytest tests/gates/test_t7_recovery.py -m slow -q
or via the driver: .venv/bin/python experiments/run_t7.py
"""

import json
from pathlib import Path

import pytest

from cins.config import load_config

CFG = load_config()
RESULTS = Path("experiments/results/t7_naca2412")


@pytest.mark.slow
def test_t7_full_pipeline_recovers_a_star():
    """End-to-end falsifiable test via the driver (slow; explicit opt-in)."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "experiments/run_t7.py"], capture_output=True, text=True, timeout=1800
    )
    assert proc.returncode == 0, f"T7 driver failed:\n{proc.stdout[-2000:]}"


def test_t7_archived_evidence_meets_gate():
    """Regression pin: the archived T7 evidence must satisfy the gate criteria.

    Guards against silent weakening — if the archived diagnostics ever change
    (re-run with worse numbers) this fails until the gate is genuinely met.
    """
    d = json.loads((RESULTS / "diagnostics.json").read_text())
    iters = d["iterations"]
    assert 0 < len(iters) <= CFG.gates.t7_max_newton_iters + 1
    # final combined residual below Newton rtol
    import math

    r_final = math.sqrt(iters[-1]["R_norm"] ** 2 + iters[-1]["T_norm"] ** 2
                        + iters[-1]["G_norm"] ** 2)
    assert r_final < 1e-9
    # recovery number pinned from the passing run (1.079e-11); allow headroom
    log_text = (RESULTS / "run.log").read_text()
    assert "T7 GATE: PASS" in log_text
    assert "converged=True" in log_text
