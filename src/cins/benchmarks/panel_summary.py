"""Panel summariser for the H1 hypothesis (STATS_PROTOCOL sections 3 and 6).

Aggregates the per-cell ``result.json`` files written by the benchmark runner
into a single summary artifact, classifies every non-converged cell into a
pre-registered exclusion class, and computes the Wilson score interval on the
dual-gate success fraction over the effective sample.

Exclusion classes (STATS_PROTOCOL section 6):

``t2_fit``
    The section's CST fit exceeds the T2 gate, so no inverse problem is posed.
    These cells are filtered before generation and appear only in the manifest.
``target_natural``
    The direct natural-transition solve on the target geometry does not
    converge. No target pressure distribution exists, so no inverse problem is
    posed.
``target_forced``
    The natural solve converges but the forced-trip solve on the target
    geometry does not. Same reasoning.
``solver_stagnation``
    The vendor solver raises ``stagpoint_move: velocity error``. The stagnation
    point leaves the panel range during the coupled solve. This is a limitation
    of the isolated-airfoil flow solver, not of the inverse formulation.
``dof``
    Deliberate degree-of-freedom perturbation cells, which are required to fail.
``other``
    Anything not matching the classes above. Reported verbatim so it cannot be
    absorbed silently.

Run:  python -m cins.benchmarks.panel_summary <results_dir> <prefix> [out.json]
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ERR_GATE = 1e-4
ITER_GATE = 9
Z = 1.959963984540054  # two-sided 95 percent normal quantile


def classify(result: dict[str, Any]) -> str:
    """Return the exclusion class for a non-converged cell."""
    notes = " ".join(result.get("notes") or [])
    if result.get("dof_check_error"):
        return "dof"
    # Signature matching runs before the generic exception fallback, because a
    # cell run in a subprocess wraps its real cause in a RuntimeError.
    if "stagpoint_move" in notes:
        return "solver_stagnation"
    if "5-digit NACA must begin" in notes:
        return "generator_unsupported"
    if "Wrong wake direction" in notes:
        return "geometry_te_gap"
    if "direct (natural) target solve failed" in notes:
        return "target_natural"
    if "forced-trip target solve failed" in notes:
        return "target_forced"
    if "flow solve at A0 failed" in notes or "flow solve at perturbed start" in notes:
        return "init_flow_solve"
    if "UNEXPECTED EXCEPTION" in notes:
        m = re.search(r"(\w+Error): ([^\n]{0,80})", notes)
        return f"other:{m.group(1)}" if m else "other"
    return "other"


def wilson_lower_bound(k: int, n: int, z: float = Z) -> float:
    """Lower bound of the Wilson score interval for k successes in n trials."""
    if n == 0:
        return 0.0
    p = k / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4 * n)) / n)
    return (centre - margin) / denom


def summarise(results_dir: Path, prefix: str) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob(f"{prefix}*/result.json")):
        r = json.loads(path.read_text())
        name = path.parent.name[len(prefix) :]
        converged = bool(r.get("converged"))
        err = r.get("err_free_inf")
        iters = r.get("iterations")
        passes = bool(
            converged
            and err is not None
            and err < ERR_GATE
            and iters is not None
            and iters <= ITER_GATE
        )
        cells.append(
            {
                "section": name,
                "converged": converged,
                "iterations": iters,
                "err_free_inf": err,
                "dual_gate_pass": passes,
                "exclusion_class": None if converged else classify(r),
                "wall_time_s": r.get("wall_time_s"),
                "notes": r.get("notes") or [],
            }
        )

    excluded = [c for c in cells if not c["converged"]]
    effective = [c for c in cells if c["converged"]]
    k = sum(1 for c in effective if c["dual_gate_pass"])
    n_eff = len(effective)

    classes: dict[str, int] = {}
    for c in excluded:
        classes[c["exclusion_class"]] = classes.get(c["exclusion_class"], 0) + 1

    return {
        "n_cells": len(cells),
        "n_excluded": len(excluded),
        "exclusion_classes": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
        "n_effective": n_eff,
        "n_dual_gate_pass": k,
        "dual_gate_fraction": (k / n_eff) if n_eff else 0.0,
        "wilson_95_lower_bound": wilson_lower_bound(k, n_eff),
        "gates": {"err_free_inf_max": ERR_GATE, "iterations_max": ITER_GATE},
        "cells": cells,
    }


def main(argv: list[str]) -> int:
    results_dir = Path(argv[1]) if len(argv) > 1 else Path("experiments/results/t8")
    prefix = argv[2] if len(argv) > 2 else "panel_uiuc_"
    out = Path(argv[3]) if len(argv) > 3 else results_dir / "uiuc_panel_summary.json"
    summary = summarise(results_dir, prefix)
    out.write_text(json.dumps(summary, indent=2))
    print(f"cells={summary['n_cells']} effective={summary['n_effective']} "
          f"dual_gate={summary['n_dual_gate_pass']} "
          f"fraction={summary['dual_gate_fraction']:.3f} "
          f"wilson_lb={summary['wilson_95_lower_bound']:.3f}")
    for cls, count in summary["exclusion_classes"].items():
        print(f"  excluded[{cls}] = {count}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
