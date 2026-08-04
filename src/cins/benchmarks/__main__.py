"""``python -m cins.benchmarks`` — T8 ablation-cell CLI (STATS_PROTOCOL §7).

    python -m cins.benchmarks run configs/experiments/t8_n08_baseline.yaml
    python -m cins.benchmarks sweep configs/experiments
    python -m cins.benchmarks control configs/experiments/t8_n08_baseline.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from cins.config import load_config

from .control import run_control
from .runner import RESULTS_ROOT, cell_name_from_path, run_cell, sweep


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(prog="python -m cins.benchmarks")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run a single T8 ablation cell")
    p_run.add_argument("config", help="path to a configs/experiments/<cell>.yaml overlay")

    p_sweep = sub.add_parser("sweep", help="run every *.yaml cell in a directory, sequentially")
    p_sweep.add_argument("directory", help="directory of cell config YAMLs")

    p_control = sub.add_parser("control", help="H2 nested scipy.least_squares baseline")
    p_control.add_argument("config", help="path to the winning-configuration cell YAML")
    p_control.add_argument("--max-nfev", type=int, default=300)

    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_cell(args.config)
        return 0 if (result.converged or result.dof_check_error is not None) else 1

    if args.command == "sweep":
        results = sweep(args.directory)
        n_ok = sum(1 for r in results if r.converged or r.dof_check_error is not None)
        logging.info("sweep: %d/%d cells completed as expected", n_ok, len(results))
        return 0 if n_ok == len(results) else 1

    if args.command == "control":
        cfg = load_config(args.config)
        cell_name = cell_name_from_path(args.config)
        result = run_control(cfg, cell_name=f"{cell_name}_control", config_path=args.config,
                              max_nfev=args.max_nfev)
        out_dir = RESULTS_ROOT / f"{cell_name}_control"
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "result.json", "w") as f:
            json.dump(result.to_dict(), f, indent=2, sort_keys=True)
        logging.info("wrote %s (converged=%s nfev=%d)", out_dir / "result.json",
                      result.converged, result.n_nfev)
        return 0 if result.converged else 1

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
