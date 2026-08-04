"""Pydantic request/response models for the CINS FastAPI app.

Mirrors the ``cins`` package's own conventions (see src/cins/CLAUDE.md): CST
coefficient vectors are ``[A_u0..A_un, A_l0..A_ln]`` (upper block first, lower
stored with its natural negative sign), Cp arrays follow mfoil's panel-node
loop order (TE-lower -> LE -> TE-upper) unless split into ``upper``/``lower``.

Errors are structured JSON via FastAPI's ``HTTPException(detail=...)``;
realisability *warnings* (a target outside the CST-representable manifold,
ADR-0004) are NOT errors — ``/api/presolve`` always returns 200 with
``realisable: false`` when the metric exceeds the configured threshold, never
raises.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


# --------------------------------------------------------------------------- #
# /api/analyze
# --------------------------------------------------------------------------- #


class TransitionSpec(BaseModel):
    """Forced-trip request (ADR-0003). ``mode="free"`` (default) leaves mfoil's
    natural e^n transition alone; ``mode="forced"`` pins the trip at
    ``xtr_upper``/``xtr_lower`` (x/c) for the duration of this one analyze call,
    guarded by the process-global mfoil lock (see app/backend/app/engine.py)."""

    mode: Literal["forced", "free"] = "free"
    xtr_upper: float = Field(0.05, gt=0.0, le=1.0)
    xtr_lower: float = Field(0.05, gt=0.0, le=1.0)


class AnalyzeRequest(BaseModel):
    naca: str | None = Field(None, description="3- or 5-digit NACA code, e.g. '2412'")
    coords: list[list[float]] | None = Field(
        None, description="[[x, y], ...] airfoil coordinates, any ordering/chord"
    )
    alpha: float = Field(..., ge=-20.0, le=20.0, description="angle of attack, degrees")
    Re: float | None = Field(None, gt=1e3, lt=1e9, description="Reynolds number; omit for inviscid")
    Ma: float = Field(
        0.0, ge=0.0, lt=0.7, description="Mach number (Karman-Tsien, subcritical only)"
    )
    transition: TransitionSpec | None = None

    @model_validator(mode="after")
    def _check_geometry(self) -> "AnalyzeRequest":
        if (self.naca is None) == (self.coords is None):
            raise ValueError("exactly one of `naca` or `coords` must be given")
        if self.naca is not None and len(self.naca.strip()) not in (4, 5):
            raise ValueError(f"naca code must be 4 or 5 digits, got {self.naca!r}")
        if self.coords is not None and len(self.coords) < 10:
            raise ValueError("coords must contain at least 10 points")
        return self


class SurfaceCp(BaseModel):
    x: list[float]
    cp: list[float]


class AnalyzeResponse(BaseModel):
    converged: bool
    cl: float
    cd: float
    cm: float
    alpha: float
    Re: float | None
    Ma: float
    x: list[float]
    cp: list[float]
    upper: SurfaceCp
    lower: SurfaceCp
    coords: list[list[float]] = Field(
        description="[[x, y], ...] geometry actually solved (mfoil's re-paneled nodes)"
    )


# --------------------------------------------------------------------------- #
# /api/fit
# --------------------------------------------------------------------------- #


class FitRequest(BaseModel):
    coords: list[list[float]] = Field(..., description="[[x, y], ...] airfoil coordinates")
    n: int = Field(8, ge=2, le=20, description="Bernstein order per surface")
    N1: float = Field(0.5, gt=0.0, lt=1.0)
    N2: float = Field(1.0, gt=0.0, le=2.0)
    te_gap: float | None = Field(None, ge=0.0, lt=0.1)

    @field_validator("coords")
    @classmethod
    def _min_points(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 10:
            raise ValueError("coords must contain at least 10 points")
        return v


class FitResponse(BaseModel):
    A_upper: list[float]
    A_lower: list[float]
    zeta_T_upper: float
    zeta_T_lower: float
    n: int
    N1: float
    N2: float
    rms: float
    gram_condition: float


# --------------------------------------------------------------------------- #
# /api/presolve
# --------------------------------------------------------------------------- #


class BaselineSpec(BaseModel):
    """Either a NACA code (fitted to ``CSTConfig.n_upper`` via ``fit_cst``) or
    explicit CST coefficients. Exactly one must be given."""

    naca: str | None = None
    A_upper: list[float] | None = None
    A_lower: list[float] | None = None
    zeta_T_upper: float | None = None
    zeta_T_lower: float | None = None

    @model_validator(mode="after")
    def _check(self) -> "BaselineSpec":
        has_naca = self.naca is not None
        has_a = self.A_upper is not None and self.A_lower is not None
        if has_naca == has_a:
            raise ValueError("baseline needs exactly one of `naca` or (`A_upper` and `A_lower`)")
        return self


class TargetCpSpec(BaseModel):
    """Target Cp curve, mfoil loop order (or any ordering with a single x-minimum
    LE). ``kind`` labels whether this Cp came from an inviscid or viscous solve —
    it only affects response labeling (ADR-0004), never the presolve math."""

    x: list[float]
    cp: list[float]
    kind: Literal["inviscid", "viscous"] = "inviscid"

    @model_validator(mode="after")
    def _check_lengths(self) -> "TargetCpSpec":
        if len(self.x) != len(self.cp):
            raise ValueError(f"x ({len(self.x)}) and cp ({len(self.cp)}) must be the same length")
        if len(self.x) < 5:
            raise ValueError("target Cp needs at least 5 stations")
        return self


class ConstraintSpec(BaseModel):
    """One linear constraint row from ``cins.cst.constraints`` (dossier §3.2-3.4)."""

    type: Literal["shared_le_radius", "le_radius", "te_wedge", "area"]
    R_LE: float | None = Field(None, gt=0.0, description="le_radius: nose radius, chords")
    beta: float | None = Field(None, description="te_wedge: half-angle, radians")
    dz_TE: float | None = Field(None, description="te_wedge: signed TE offset, chords")
    side: Literal["upper", "lower"] = "upper"
    target_area: float | None = Field(None, description="area: target inscribed area, chords^2")


class PresolveRequest(BaseModel):
    baseline: BaselineSpec
    target: TargetCpSpec
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    n: int = Field(8, ge=2, le=20, description="Bernstein order (only used for a `naca` baseline)")


class PresolveResponse(BaseModel):
    A_upper_init: list[float]
    A_lower_init: list[float]
    delta_A: list[float]
    realisability: float
    realisability_label: str
    realisable: bool
    kkt_cond: float
    target_kind: str
    model_gap: float | None
    n_stations: int


# --------------------------------------------------------------------------- #
# /api/inverse
# --------------------------------------------------------------------------- #


class InverseRequest(BaseModel):
    """Self-consistency ("naca_target") inverse: generate a target Cp from
    ``airfoil`` (T7-style, ``cins.benchmarks.pipeline.prepare_cell``), then try
    to recover its CST coefficients via the monolithic Newton solve. A raw
    user-drawn Cp target mode is deferred — see app/README.md ("what's
    deferred") — the frontend Inverse view is a stub for this same reason."""

    mode: Literal["naca_target"] = "naca_target"
    airfoil: str = Field("2412", description="NACA code the target Cp is generated from")
    alpha_deg: float = Field(2.0, ge=-20.0, le=20.0)
    Re: float = Field(1.0e6, gt=1e3, lt=1e9)
    Ma: float = Field(0.0, ge=0.0, lt=0.7)
    n_upper: int | None = Field(None, ge=2, le=20)
    n_lower: int | None = Field(None, ge=2, le=20)
    le_treatment: Literal["none", "lem", "prescribed"] | None = None
    transition_mode: Literal["forced", "free"] | None = None
    alpha_free: bool = False
    station_selection: Literal["qr_pivot", "even"] = "qr_pivot"
    init: Literal["presolve", "perturbed", "random"] = "presolve"
    dof_offset: Literal[-1, 0, 1] = 0

    @field_validator("airfoil")
    @classmethod
    def _naca_len(cls, v: str) -> str:
        if len(v.strip()) not in (4, 5):
            raise ValueError(f"naca code must be 4 or 5 digits, got {v!r}")
        return v


class InverseSubmitResponse(BaseModel):
    job_id: str
    status: str


class InverseResultPayload(BaseModel):
    converged: bool
    iterations: int
    alpha: float | None = None
    A_upper: list[float] | None = None
    A_lower: list[float] | None = None
    coords: list[list[float]] | None = None
    residual_history: list[float]
    convergence_order: float | None
    release_verify: dict[str, Any] | None
    realisability: float | None
    model_gap: float | None
    submap_cond: float | None
    notes: list[str]
    dof_check_error: str | None = None
    wall_time_s: float
    diagnostics: list[dict[str, Any]]
    manifest: dict[str, Any] | None = None


class InverseJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    result: InverseResultPayload | None = None
    error: str | None = None
