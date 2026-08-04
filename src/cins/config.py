"""CINS configuration schema — the single source of truth for run parameters.

Every numeric parameter in the codebase traces to a YAML file validated here.
Gate thresholds live in the same schema so tests and runtime cannot diverge.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "default.yaml"


class CSTConfig(BaseModel):
    n_upper: int = Field(ge=2, le=20)
    n_lower: int = Field(ge=2, le=20)
    N1: float = Field(gt=0.0, lt=1.0)
    N2: float = Field(gt=0.0, le=2.0)
    te_gap: float = Field(ge=0.0, lt=0.1)
    le_treatment: Literal["none", "lem", "prescribed"]
    prescribed_le_fraction: float = Field(gt=0.0, lt=0.5)


class PanelingConfig(BaseModel):
    npanel: int = Field(ge=50, le=1000)
    spacing: Literal["cosine", "uniform"]


class OperatingConfig(BaseModel):
    alpha_deg: float = Field(ge=-20.0, le=20.0)
    Re: float = Field(gt=1e3, lt=1e9)
    Ma: float = Field(ge=0.0, lt=0.7)  # Karman-Tsien: subcritical only
    viscous: bool


class TransitionConfig(BaseModel):
    mode: Literal["forced", "free"]
    xtr_upper: float = Field(gt=0.0, le=1.0)
    xtr_lower: float = Field(gt=0.0, le=1.0)
    ncrit: float = Field(gt=0.0, le=20.0)


class NewtonConfig(BaseModel):
    rtol: float = Field(gt=0.0)
    max_iter: int = Field(ge=1, le=500)
    a_trust_radius: float = Field(gt=0.0)
    derivative_mode: Literal["auto", "analytic", "complex_step", "finite_difference"]
    fd_step: float = Field(gt=0.0)
    cs_step: float = Field(gt=0.0)


class PresolveConfig(BaseModel):
    realisability_threshold: float = Field(gt=0.0, lt=1.0)
    fd_step: float = Field(
        gt=0.0,
        description=(
            "Central-difference step on a CST coefficient A_i when building "
            "the T4 sensitivity matrix M (dossier §7.5). Separate from "
            "newton.fd_step: T4 perturbs CST coefficients feeding a single "
            "*inviscid* (non-iterative) solve, so there is no Newton-noise "
            "floor forcing a tiny step; O(1e-3) balances FD truncation error "
            "against the nonlinearity of Cp(A) over the step."
        ),
    )


class GatesConfig(BaseModel):
    """Numeric gate criteria from the dossier (§7). Changing any value needs an ADR."""

    t0_cl_range: tuple[float, float]
    t2_fit_rms_max: float = Field(gt=0.0)
    t3_area_quadrature_tol: float = Field(gt=0.0)
    t7_a_recovery_inf_norm: float = Field(gt=0.0)
    t7_max_newton_iters: int = Field(ge=1, le=9, description="single-digit per dossier")


class ExperimentConfig(BaseModel):
    seed: int
    results_dir: str


class DiagnosticsConfig(BaseModel):
    """T6 diagnostics instrumentation (dossier §7.7 / SPEC.md §6)."""

    compute_expensive: bool = True
    dense_rank_max_dim: int = Field(ge=1, le=100_000)


class CinsConfig(BaseModel):
    cst: CSTConfig
    paneling: PanelingConfig
    operating: OperatingConfig
    transition: TransitionConfig
    newton: NewtonConfig
    presolve: PresolveConfig
    gates: GatesConfig
    experiment: ExperimentConfig
    diagnostics: DiagnosticsConfig

    @model_validator(mode="after")
    def _check_dof_feasible(self) -> "CinsConfig":
        # n_A = 2(n+1) coefficient count must leave room for constraints + targets
        n_a = (self.cst.n_upper + 1) + (self.cst.n_lower + 1)
        if n_a < 6:
            raise ValueError(f"n_A={n_a} too small for DOF accounting (need >= 6)")
        return self

    def config_hash(self) -> str:
        """Stable hash of the validated config, for experiment manifests."""
        canon = yaml.safe_dump(self.model_dump(), sort_keys=True)
        return hashlib.sha256(canon.encode()).hexdigest()[:16]


def load_config(path: str | Path = DEFAULT_CONFIG) -> CinsConfig:
    """Load and validate a CINS config YAML. Overlay files may specify a subset;

    subsets are deep-merged over default.yaml."""
    path = Path(path)
    with open(DEFAULT_CONFIG) as f:
        base = yaml.safe_load(f)
    if path.resolve() != DEFAULT_CONFIG.resolve():
        with open(path) as f:
            overlay = yaml.safe_load(f) or {}
        base = _deep_merge(base, overlay)
    return CinsConfig.model_validate(base)


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
