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

# Exclusion classes in which no inverse problem was ever posed, so the cell
# cannot count for or against the method. Every other non-converged class is a
# failure of the attempt and stays in the attempted denominator.
NOT_POSED = frozenset({"t2_fit", "target_natural", "target_forced", "init_flow_solve"})
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
    not_posed = [c for c in excluded if c["exclusion_class"] in NOT_POSED]
    attempt_failures = [c for c in excluded if c["exclusion_class"] not in NOT_POSED]
    converged = [c for c in cells if c["converged"]]

    n_attempted = len(converged) + len(attempt_failures)
    k_dual = sum(1 for c in converged if c["dual_gate_pass"])
    k_acc = sum(
        1 for c in converged
        if c["err_free_inf"] is not None and c["err_free_inf"] < ERR_GATE
    )
    k_iter = sum(
        1 for c in converged
        if c["iterations"] is not None and c["iterations"] <= ITER_GATE
    )

    classes: dict[str, int] = {}
    for c in excluded:
        classes[c["exclusion_class"]] = classes.get(c["exclusion_class"], 0) + 1

    return {
        "n_cells": len(cells),
        "n_not_posed": len(not_posed),
        "n_attempt_failures": len(attempt_failures),
        "n_attempted": n_attempted,
        "n_converged": len(converged),
        "exclusion_classes": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
        # Accuracy and iteration budget are reported separately because they
        # fail for different reasons and carry different weight.
        "accuracy_among_converged": {
            "k": k_acc, "n": len(converged),
            "fraction": (k_acc / len(converged)) if converged else 0.0,
            "wilson_95_lower_bound": wilson_lower_bound(k_acc, len(converged)),
        },
        "iteration_budget_among_converged": {
            "k": k_iter, "n": len(converged),
            "fraction": (k_iter / len(converged)) if converged else 0.0,
            "wilson_95_lower_bound": wilson_lower_bound(k_iter, len(converged)),
        },
        "dual_gate_among_converged": {
            "k": k_dual, "n": len(converged),
            "fraction": (k_dual / len(converged)) if converged else 0.0,
            "wilson_95_lower_bound": wilson_lower_bound(k_dual, len(converged)),
        },
        "dual_gate_among_attempted": {
            "k": k_dual, "n": n_attempted,
            "fraction": (k_dual / n_attempted) if n_attempted else 0.0,
            "wilson_95_lower_bound": wilson_lower_bound(k_dual, n_attempted),
        },
        "gates": {"err_free_inf_max": ERR_GATE, "iterations_max": ITER_GATE},
        "cells": cells,
    }


def main(argv: list[str]) -> int:
    results_dir = Path(argv[1]) if len(argv) > 1 else Path("experiments/results/t8")
    prefix = argv[2] if len(argv) > 2 else "panel_uiuc_"
    out = Path(argv[3]) if len(argv) > 3 else results_dir / "uiuc_panel_summary.json"
    summary = summarise(results_dir, prefix)
    out.write_text(json.dumps(summary, indent=2))
    print(f"cells={summary['n_cells']} not_posed={summary['n_not_posed']} "
          f"attempt_failures={summary['n_attempt_failures']} "
          f"attempted={summary['n_attempted']} converged={summary['n_converged']}")
    for key in ("accuracy_among_converged", "iteration_budget_among_converged",
                "dual_gate_among_converged", "dual_gate_among_attempted"):
        b = summary[key]
        print(f"  {key}: {b['k']}/{b['n']} = {b['fraction']:.3f} "
              f"(Wilson 95% LB {b['wilson_95_lower_bound']:.3f})")
    for cls, count in summary["exclusion_classes"].items():
        print(f"  excluded[{cls}] = {count}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
