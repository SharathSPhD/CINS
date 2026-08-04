"""T8 ablation-cell runner (STATS_PROTOCOL §7): the CLI-facing layer over
``pipeline.run_pipeline``.

``run_cell`` loads one cell config (a ``configs/experiments/<cell>.yaml``
overlay, per ``cins.config.load_config``'s deep-merge), runs the pipeline, and
writes ``experiments/results/t8/<cellname>/result.json`` — the manifest +
metrics contract STATS_PROTOCOL §7 requires for regenerability. ``sweep`` runs
every ``*.yaml`` cell in a directory sequentially, isolating one cell's
failure from the rest (a cell that raises is captured as a failed
``CellResult``, not a crashed sweep — operational robustness on top of
``pipeline.py``'s explicit, in-protocol FM-1 clean-failure handling).
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path

from cins.config import REPO_ROOT, CinsConfig, load_config

from .pipeline import CellResult, run_pipeline

__all__ = ["run_cell", "sweep", "cell_name_from_path"]

log = logging.getLogger(__name__)

RESULTS_ROOT = REPO_ROOT / "experiments" / "results" / "t8"


def cell_name_from_path(config_path: str | Path) -> str:
    return Path(config_path).stem


def _write_result(result: CellResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "result.json"
    with open(out_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2, sort_keys=True)
    return out_path


def run_cell(
    config_path: str | Path,
    *,
    results_root: str | Path | None = None,
    cfg: CinsConfig | None = None,
) -> CellResult:
    """Run one T8 ablation cell and write its ``result.json``.

    ``cfg`` may be passed directly (tests inject a pre-built/mocked config);
    otherwise it is loaded from ``config_path`` via the standard
    ``configs/default.yaml`` overlay mechanism.
    """
    config_path = Path(config_path)
    cell_name = cell_name_from_path(config_path)
    results_root = Path(results_root) if results_root is not None else RESULTS_ROOT
    out_dir = results_root / cell_name

    cfg = cfg if cfg is not None else load_config(config_path)
    log.info("=== T8 cell: %s ===", cell_name)
    result = run_pipeline(cfg, cell_name=cell_name, config_path=config_path, run_dir=str(out_dir))
    out_path = _write_result(result, out_dir)
    log.info("wrote %s (converged=%s iters=%d)", out_path, result.converged, result.iterations)
    return result


def sweep(
    config_dir: str | Path,
    *,
    results_root: str | Path | None = None,
) -> list[CellResult]:
    """Run every ``*.yaml`` cell config in ``config_dir``, sequentially.

    A cell whose pipeline raises an *unexpected* exception (i.e. not the
    designed FM-1 dof_offset failure, which ``run_pipeline`` already converts
    to a clean ``CellResult``) is recorded as a failed ``CellResult`` with the
    traceback in ``notes``, and the sweep continues — one bad cell must not
    silently drop the rest of the matrix.
    """
    config_dir = Path(config_dir)
    paths = sorted(config_dir.glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"no *.yaml cell configs found in {config_dir}")

    results: list[CellResult] = []
    for path in paths:
        cell_name = cell_name_from_path(path)
        try:
            result = run_cell(path, results_root=results_root)
        except Exception:  # noqa: BLE001 - operational sweep robustness, see docstring
            tb = traceback.format_exc()
            log.error("T8 cell %s crashed:\n%s", cell_name, tb)
            results_root_p = Path(results_root) if results_root is not None else RESULTS_ROOT
            result = CellResult(
                cell_name=cell_name,
                manifest={"cell_name": cell_name, "config_path": str(path)},
                converged=False,
                iterations=0,
                err_free_inf=None,
                err_all_inf=None,
                residual_history=[],
                convergence_order=None,
                n_residual_evaluations=0,
                n_flow_solves_equivalent=0,
                release_verify=None,
                realisability=None,
                model_gap=None,
                submap_cond=None,
                wall_time_s=0.0,
                notes=[f"UNEXPECTED EXCEPTION: {tb}"],
            )
            _write_result(result, results_root_p / cell_name)
        results.append(result)
    return results
