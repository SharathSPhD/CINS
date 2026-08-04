"""T6 diagnostics instrumentation (dossier §7.7, SPEC.md §6) — the contract T5's
Newton solver codes against.

``NewtonDiagnostics`` is instantiated once per solve and fed per-iteration data via
``record_iteration`` (D-1, D-2, D-4, D-5 raw material) and once-per-run static data
via ``record_static`` (D-3, FM-1 DOF bookkeeping). ``finalize`` writes the JSON
artifact (mirroring the manifest pattern in
``experiments/results/t2_gram_conditioning.json``) and returns a ``DiagnosticsReport``.

All expensive linear-algebra (dense SVD for rank/cond, D-4 row norms) is gated by
``diagnostics.compute_expensive`` in the config so a production Newton loop can
disable it, and by ``diagnostics.dense_rank_max_dim`` so a large Jacobian falls back
to a cheap norm-based conditioning *estimate* rather than a dense SVD.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import onenormest

from cins.config import REPO_ROOT, CinsConfig, DiagnosticsConfig, load_config

logger = logging.getLogger(__name__)


def _to_dense_if_small(matrix: Any, max_dim: int) -> np.ndarray | None:
    """Return a dense ndarray copy of ``matrix`` if its larger dimension is within
    ``max_dim``, else None. Accepts scipy sparse matrices or dense array-likes."""
    if matrix is None:
        return None
    shape = matrix.shape
    if max(shape) > max_dim:
        return None
    if sp.issparse(matrix):
        return np.asarray(matrix.todense())
    return np.asarray(matrix)


def _rank_and_cond(matrix: Any, max_dim: int) -> tuple[int | None, float | None]:
    """D-2 rank/cond of an arbitrary 2D matrix (dense or scipy sparse).

    Below ``max_dim`` (the larger matrix dimension): exact rank via dense SVD
    (``np.linalg.matrix_rank``) and ``cond = sigma_max / sigma_min``.

    Above ``max_dim``: a dense SVD is too expensive, so rank is not computed
    (returned as None) and cond is a cheap *estimate* — the ratio of a 1-norm
    estimate of the matrix (``scipy.sparse.linalg.onenormest``) to a 1-norm
    estimate of its pseudo-inverse action is not generally available without a
    factorization, so we instead report the 1-norm-based condition estimate
    ``cond_1 ~= onenormest(A) * onenormest(A^+)`` when a sparse LU factorization
    is feasible, falling back to just ``onenormest(A)`` (an upper bound on the
    matrix's scale, not a true condition number) if factorization fails. This
    is documented as an *estimate*, not an exact bound — callers needing an
    exact rank/cond on a large Jacobian should subsample or use a dedicated
    sparse SVD (``scipy.sparse.linalg.svds``).
    """
    dense = _to_dense_if_small(matrix, max_dim)
    if dense is not None:
        s = np.linalg.svd(dense, compute_uv=False)
        rank = int(np.sum(s > s.max() * max(dense.shape) * np.finfo(dense.dtype).eps))
        cond = float(s.max() / s.min()) if s.min() > 0 else float("inf")
        return rank, cond

    # Large matrix: skip exact rank, estimate condition cheaply.
    try:
        mat = matrix.tocsc() if sp.issparse(matrix) else sp.csc_matrix(matrix)
        norm_a = onenormest(mat)
        lu = sp.linalg.splu(mat.tocsc())

        class _InvOp(sp.linalg.LinearOperator):
            def __init__(self, lu_, shape):
                super().__init__(dtype=mat.dtype, shape=shape)
                self._lu = lu_

            def _matvec(self, x):
                return self._lu.solve(x)

        norm_ainv = onenormest(_InvOp(lu, mat.shape))
        cond = float(norm_a * norm_ainv)
    except Exception:
        logger.warning(
            "D-2: large matrix (dim > %d), factorization failed; falling back to "
            "onenormest(A) only (not a true condition number).",
            max_dim,
        )
        try:
            fallback_mat = matrix.tocsc() if sp.issparse(matrix) else sp.csc_matrix(matrix)
            cond = float(onenormest(fallback_mat))
        except Exception:
            cond = None
    return None, cond


@dataclass
class IterationRecord:
    """One Newton iteration's diagnostic snapshot."""

    it: int
    R_norm: float
    T_norm: float
    G_norm: float
    rank_J: int | None = None
    cond_J: float | None = None
    rank_RA_G: int | None = None
    dR_dA_row_norms: list[float] | None = None
    x_stations: list[float] | None = None
    transition_xt: Any | None = None
    omega: float | None = None
    dA_norm: float | None = None
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IterationRecord":
        return cls(**d)


@dataclass
class DiagnosticsReport:
    """Everything ``finalize`` writes to disk, plus the derived D-6 estimate."""

    iterations: list[IterationRecord]
    gram_condition: float | None
    dof_accounting: dict[str, Any] | None
    manifest: dict[str, Any]
    convergence_order: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest,
            "static": {
                "gram_condition": self.gram_condition,
                "dof_accounting": self.dof_accounting,
            },
            "convergence_order": self.convergence_order,
            "iterations": [r.to_dict() for r in self.iterations],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DiagnosticsReport":
        static = d.get("static", {})
        return cls(
            iterations=[IterationRecord.from_dict(r) for r in d.get("iterations", [])],
            gram_condition=static.get("gram_condition"),
            dof_accounting=static.get("dof_accounting"),
            manifest=d.get("manifest", {}),
            convergence_order=d.get("convergence_order"),
        )

    @classmethod
    def load(cls, path: str | Path) -> "DiagnosticsReport":
        with open(path) as f:
            return cls.from_dict(json.load(f))


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


@dataclass
class NewtonDiagnostics:
    """Per-solve instrumentation contract T5's Newton solver codes against.

    Usage::

        diag = NewtonDiagnostics(config=cfg)
        diag.record_static(gram_condition=..., dof_accounting={...})
        for it in range(max_iter):
            ...
            diag.record_iteration(it, R_norm=..., T_norm=..., G_norm=...,
                                   jacobian=J, dR_dA=dR_dA, x_stations=x)
        report = diag.finalize(run_dir, run_manifest={"airfoil": "2412"})
    """

    config: CinsConfig | DiagnosticsConfig | None = None
    compute_expensive: bool | None = None
    dense_rank_max_dim: int | None = None

    _iterations: list[IterationRecord] = field(default_factory=list, init=False)
    _gram_condition: float | None = field(default=None, init=False)
    _dof_accounting: dict[str, Any] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        diag_cfg: DiagnosticsConfig
        if isinstance(self.config, CinsConfig):
            diag_cfg = self.config.diagnostics
        elif isinstance(self.config, DiagnosticsConfig):
            diag_cfg = self.config
        else:
            diag_cfg = load_config().diagnostics
        if self.compute_expensive is None:
            self.compute_expensive = diag_cfg.compute_expensive
        if self.dense_rank_max_dim is None:
            self.dense_rank_max_dim = diag_cfg.dense_rank_max_dim

    # ------------------------------------------------------------------ #
    # Recording
    # ------------------------------------------------------------------ #
    def record_iteration(
        self,
        it: int,
        *,
        R_norm: float,
        T_norm: float,
        G_norm: float,
        jacobian: Any | None = None,
        dR_dA: Any | None = None,
        x_stations: Any | None = None,
        transition_xt: Any | None = None,
        omega: float | None = None,
        dA_norm: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> IterationRecord:
        """Capture one Newton iteration.

        ``jacobian`` (dense or scipy-sparse) triggers D-2 (rank/cond) when
        ``compute_expensive`` is True. ``dR_dA`` together with ``x_stations``
        (one chordwise station per row of ``dR_dA``) triggers D-4 (row-norm
        profile vs chordwise station).
        """
        rank_j = cond_j = None
        rank_ra_g = None
        row_norms = None
        stations = None

        if self.compute_expensive:
            if jacobian is not None:
                rank_j, cond_j = _rank_and_cond(jacobian, self.dense_rank_max_dim)
            if dR_dA is not None:
                rank_ra_g, _ = _rank_and_cond(dR_dA, self.dense_rank_max_dim)
                dR_dA_dense = np.asarray(
                    dR_dA.todense() if sp.issparse(dR_dA) else dR_dA
                )
                row_norms = np.linalg.norm(dR_dA_dense, axis=1).tolist()
                if x_stations is not None:
                    stations = list(np.asarray(x_stations, dtype=float))

        record = IterationRecord(
            it=int(it),
            R_norm=float(R_norm),
            T_norm=float(T_norm),
            G_norm=float(G_norm),
            rank_J=rank_j,
            cond_J=cond_j,
            rank_RA_G=rank_ra_g,
            dR_dA_row_norms=row_norms,
            x_stations=stations,
            transition_xt=transition_xt,
            omega=omega,
            dA_norm=dA_norm,
            extra=extra,
        )
        self._iterations.append(record)
        return record

    def record_static(
        self,
        *,
        gram_condition: float | None = None,
        dof_accounting: dict[str, Any] | None = None,
    ) -> None:
        """D-3 (Gram-matrix conditioning) and FM-1 DOF bookkeeping
        (``n_A``, ``M``, ``K``, squareness residual = ``M + K - (n_A + 1)``)."""
        if gram_condition is not None:
            self._gram_condition = float(gram_condition)
        if dof_accounting is not None:
            self._dof_accounting = dict(dof_accounting)

    # ------------------------------------------------------------------ #
    # D-6
    # ------------------------------------------------------------------ #
    def convergence_order_estimate(self, floor: float | None = None) -> float | None:
        """D-6 quadratic-tail estimator (dossier §7.7, STATS_PROTOCOL.md H3).

        ``p ~= log(||R_k|| / ||R_{k-1}||) / log(||R_{k-1}|| / ||R_{k-2}||)``
        computed over the final 3 iterations' R_norm, in iteration order.

        ``floor`` (if given) excludes iterations whose R_norm is at or below
        the solver's convergence floor before selecting the final 3 points,
        per STATS_PROTOCOL.md's instruction to exclude iterations where the
        residual is already at machine-precision noise. Returns None if fewer
        than 3 usable points are available (handles short histories).
        """
        records = sorted(self._iterations, key=lambda r: r.it)
        r_norms = [r.R_norm for r in records]
        if floor is not None:
            r_norms = [r for r in r_norms if r > floor]
        if len(r_norms) < 3:
            return None
        r_k2, r_k1, r_k = r_norms[-3], r_norms[-2], r_norms[-1]
        if r_k2 <= 0 or r_k1 <= 0 or r_k <= 0:
            return None
        denom = np.log(r_k1 / r_k2)
        if denom == 0:
            return None
        p = np.log(r_k / r_k1) / denom
        return float(p)

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #
    def finalize(
        self, run_dir: str | Path, run_manifest: dict[str, Any] | None = None
    ) -> DiagnosticsReport:
        """Write the JSON diagnostics artifact to ``run_dir/diagnostics.json``
        (mirroring the manifest pattern in
        ``experiments/results/t2_gram_conditioning.json``) and return the
        in-memory ``DiagnosticsReport``."""
        cfg = self.config if isinstance(self.config, CinsConfig) else load_config()
        manifest = {
            "git_sha": _git_sha(),
            "config_hash": cfg.config_hash(),
            "timestamp_utc": datetime.now(UTC).isoformat(),
        }
        manifest.update(run_manifest or {})

        report = DiagnosticsReport(
            iterations=list(self._iterations),
            gram_condition=self._gram_condition,
            dof_accounting=self._dof_accounting,
            manifest=manifest,
            convergence_order=self.convergence_order_estimate(),
        )

        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        out_path = run_dir / "diagnostics.json"
        out_path.write_text(json.dumps(report.to_dict(), indent=2))
        logger.info("NewtonDiagnostics.finalize: wrote %s", out_path)
        return report
