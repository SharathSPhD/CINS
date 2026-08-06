"""T7 falsifiable test driver (dossier §7.8) — thin wrapper.

1. Fit CST (n=8) to NACA 2412 -> A*.
2. Build the CST geometry, direct-solve viscous WITH forced trip -> Cp_target.
3. Perturb A* -> A0; run the monolithic inverse.
4. Success: ||A - A*||_inf < 1e-4, single-digit iterations, quadratic tail.

The pipeline logic (steps 1-4, release-and-verify) now lives in
``cins.benchmarks.pipeline.run_pipeline`` (T8 infrastructure refactor) so the
T7 and T8-ablation-cell drivers share one implementation; this module is
behaviorally identical to the pre-refactor version — same config
(``configs/default.yaml``, unmodified: ``t8.airfoil=2412``,
``t8.station_selection=qr_pivot``, ``t8.init=presolve``, ``t8.alpha_free=false``,
``t8.dof_offset=0`` are exactly the T7 settings), same gate logic, same log
lines, same exit code.

Run: .venv/bin/python experiments/run_t7.py [--verbose]
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cins.benchmarks.pipeline import run_pipeline
from cins.config import load_config


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("t7")


def main() -> int:
    cfg = load_config()
    result = run_pipeline(
        cfg, cell_name="t7_naca2412_selfconsistent", run_dir="experiments/results/t7_naca2412"
    )

    log.info(
        "RESULT: converged=%s iters=%d ||A-A*||_inf(free)=%.3e (all=%.3e) order=%s",
        result.converged, result.iterations,
        result.err_free_inf if result.err_free_inf is not None else float("nan"),
        result.err_all_inf if result.err_all_inf is not None else float("nan"),
        result.convergence_order,
    )
    log.info("residual history: %s", ["%.2e" % r for r in result.residual_history])

    verify_ok = bool(result.release_verify and result.release_verify.get("ok"))
    if result.release_verify:
        rv = result.release_verify
        log.info(
            "release-and-verify (natural transition): cl=%.6f (target %.6f, d=%.1e) "
            "cd=%.6f (target %.6f, d=%.1e) conv=%s",
            rv["cl"], rv["cl_target"], rv["dcl"], rv["cd"], rv["cd_target"], rv["dcd"],
            rv["converged"],
        )

    ok = (
        result.converged
        and result.err_free_inf is not None
        and result.err_free_inf < cfg.gates.t7_a_recovery_inf_norm
        and result.iterations <= cfg.gates.t7_max_newton_iters
        and verify_ok
    )
    log.info(
        "T7 GATE: %s (recovery %s, release-verify %s)",
        "PASS" if ok else "FAIL",
        "ok" if (result.err_free_inf is not None
                  and result.err_free_inf < cfg.gates.t7_a_recovery_inf_norm) else "FAIL",
        "ok" if verify_ok else "FAIL",
    )

    # Archive the summary alongside the per-iteration diagnostics. Without
    # this, the numbers the paper quotes for T7 (err_free_inf, the
    # release-and-verify deltas, the iteration count) existed only in console
    # output, while ``run.log`` in the same directory could still hold an
    # older run's values. Both audits of the manuscript flagged the resulting
    # artifact disagreement, so the summary is now written every run.
    out = Path("experiments/results/t7_naca2412/result.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    payload["gate"] = {
        "passed": bool(ok),
        "recovery_threshold": float(cfg.gates.t7_a_recovery_inf_norm),
        "max_newton_iters": int(cfg.gates.t7_max_newton_iters),
    }
    payload.setdefault("manifest", {})
    payload["manifest"].update({
        "config_hash": cfg.config_hash(),
        "git_sha": _git_sha(),
        "station_addressing": "surface_x_interpolated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    log.info("wrote %s", out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
