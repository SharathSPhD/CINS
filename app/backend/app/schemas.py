"""Pydantic request/response models for the CINS FastAPI app.

Mirrors the ``cins`` package's own conventions (see src/cins/CLAUDE.md): CST
coefficient vectors are ``[A_u0..A_un, A_l0..A_ln]`` (upper block first, lower
stored with its natural negative sign), Cp arrays follow mfoil's panel-node
loop order (TE-lower -> LE -> TE-upper) unless split into ``upper``/``lower``.

Errors are structured JSON via FastAPI's ``HTTPException(detail=...)``;
realisability *warnings* (a target outside the CST-representable manifold,
ADR-0004) are NOT errors: ``/api/presolve`` always returns 200 with
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
    npanel: int | None = Field(
        None, ge=50, le=1000,
        description=(
            "panel count; omit for the interactive default "
            "(paneling.npanel_interactive), pass the study count to reproduce "
            "the manuscript"
        ),
    )

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


class SurfaceSplit(BaseModel):
    upper: list[float]
    lower: list[float]


class BLDistributions(BaseModel):
    """Viscous boundary-layer distributions, per surface, x-ascending (mfoil's
    ``post.{th,ds,sa,ue,uei,cf,Ret,Hk}``: momentum thickness, displacement
    thickness, amplification factor/shear-lag coefficient, edge velocity
    (viscous/inviscid), skin friction, Re_theta, kinematic shape factor ,
    the full set ``m.plot_distributions`` offers), plus the e^n transition
    location. Present only for a converged viscous (``Re`` given) solve."""

    x: SurfaceSplit
    theta: SurfaceSplit
    delta_star: SurfaceSplit
    cf: SurfaceSplit
    Hk: SurfaceSplit
    amplification: SurfaceSplit
    ue: SurfaceSplit
    uei: SurfaceSplit
    Re_theta: SurfaceSplit
    transition_x: dict[str, float] | None = None


class AnalyzeResponse(BaseModel):
    converged: bool
    cl: float
    cd: float
    cm: float
    cdf: float | None = Field(None, description="skin-friction drag coefficient (viscous only)")
    cdp: float | None = Field(None, description="pressure drag coefficient (viscous only)")
    alpha: float
    Re: float | None
    Ma: float
    x: list[float]
    cp: list[float]
    upper: SurfaceCp
    lower: SurfaceCp
    upper_cpi: SurfaceCp | None = Field(
        None, description="inviscid Cp overlay, upper surface (mfoil plot_cpplus dashed curve)"
    )
    lower_cpi: SurfaceCp | None = Field(
        None, description="inviscid Cp overlay, lower surface (mfoil plot_cpplus dashed curve)"
    )
    sonic_cp: float | None = Field(
        None, description="sonic Cp (m.param.cps); set only when Ma>0 and within the Cp range"
    )
    coords: list[list[float]] = Field(
        description="[[x, y], ...] geometry actually solved (mfoil's re-paneled nodes)"
    )
    bl: BLDistributions | None = None
    bl_offset: dict[str, list[list[float]]] | None = Field(
        None,
        description="airfoil surface offset by delta* along outward normals (mfoil "
        "mplot_boundary_layer): {'upper': [[x,y],...], 'lower': [[x,y],...]}",
    )
    npanel: int | None = Field(
        None, description="panel count actually solved, so the interactive "
        "default is visible rather than assumed to be the study count"
    )
    cached: bool = Field(
        False, description="served from the in-process result cache without re-solving"
    )


class AnalyzeSubmitResponse(BaseModel):
    job_id: str
    status: str


class AnalyzeJobResponse(BaseModel):
    job_id: str
    status: str
    result: AnalyzeResponse | None = None
    error: str | None = None
    phase: str | None = None


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


class DerivedGeometry(BaseModel):
    """Named engineering quantities computed from CST coefficients (closed-form,
    no quadrature: dossier §3.2-3.4): LE radius (R_LE = A_u0^2/2), TE wedge
    half-angles (from the exact TE-slope identity, N2=1), thickness/camber
    envelopes on a fine psi grid, and inscribed area (Beta-function row)."""

    le_radius: float
    te_wedge_upper_deg: float
    te_wedge_lower_deg: float
    te_gap: float
    max_thickness: float
    max_thickness_x: float
    max_camber: float
    max_camber_x: float
    area: float


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
    derived: DerivedGeometry


# --------------------------------------------------------------------------- #
# /api/airfoils, /api/geometry/from-cst
# --------------------------------------------------------------------------- #


class AirfoilListItem(BaseModel):
    id: str
    name: str
    source: Literal["uiuc", "naca"]
    thickness: float | None = None
    camber: float | None = None
    n_points: int | None = None


class AirfoilListResponse(BaseModel):
    uiuc: list[AirfoilListItem]
    naca: list[AirfoilListItem]


class AirfoilGeometryResponse(BaseModel):
    id: str
    coords: list[list[float]]


class AirfoilUploadResponse(BaseModel):
    """Response for POST /api/airfoils/upload (item 6): a user-supplied
    ``.dat`` file, parsed + fitted, ready to drive Analyze/FlowField/Inverse."""

    id: str
    name: str
    coords: list[list[float]]
    n_points: int
    fit: FitResponse


class GeometryFromCSTRequest(BaseModel):
    A_upper: list[float] = Field(..., min_length=2)
    A_lower: list[float] = Field(..., min_length=2)
    zeta_T_upper: float = 0.0
    zeta_T_lower: float = 0.0
    N1: float = Field(0.5, gt=0.0, lt=1.0)
    N2: float = Field(1.0, gt=0.0, le=2.0)
    npoint: int = Field(161, ge=21, le=801, description="points per side (cosine spacing)")


class GeometryFromCSTResponse(BaseModel):
    coords: list[list[float]]
    derived: DerivedGeometry


# --------------------------------------------------------------------------- #
# /api/flowfield
# --------------------------------------------------------------------------- #


class FlowFieldGrid(BaseModel):
    # Defaults raised from 60x40 now that /api/flowfield uses the vectorized
    # evaluator (app/backend/app/flowfield.py): 120x80 renders a visibly
    # sharper picture and is still ~0.35s locally (measured), well inside
    # engine._FLOWFIELD_MAX_CELLS's live-response budget.
    # 60x40 measures ~8.5 s on the free-tier backend; 120x80 is four times
    # the cells and lands past the client timeout, so it is available on
    # request but is not the default.
    nx: int = Field(60, ge=5, le=200)
    ny: int = Field(40, ge=5, le=200)
    x_min: float = -0.5
    x_max: float = 1.5
    y_min: float = -0.6
    y_max: float = 0.6


class FlowFieldRequest(BaseModel):
    naca: str | None = None
    coords: list[list[float]] | None = None
    alpha: float = Field(2.0, ge=-20.0, le=20.0)
    Ma: float = Field(0.0, ge=0.0, lt=0.7)
    grid: FlowFieldGrid = Field(default_factory=FlowFieldGrid)

    @model_validator(mode="after")
    def _check_geometry(self) -> "FlowFieldRequest":
        if (self.naca is None) == (self.coords is None):
            raise ValueError("exactly one of `naca` or `coords` must be given")
        return self


class FlowFieldResponse(BaseModel):
    x: list[float]
    y: list[float]
    u: list[list[float | None]]
    v: list[list[float | None]]
    speed: list[list[float | None]]
    cp: list[list[float | None]]
    airfoil: list[list[float]]
    alpha: float
    Vinf: float
    nx: int
    ny: int
    note: str = (
        "inviscid velocity field (vendor mfoil.inviscid_velocity) at fixed "
        "circulation from the alpha given; grid points inside the airfoil "
        "body are null."
    )


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
    LE). ``kind`` labels whether this Cp came from an inviscid or viscous solve ,
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
    user-drawn Cp target mode is deferred: see app/README.md ("what's
    deferred"): the frontend Inverse view is a stub for this same reason."""

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


class InverseStage(BaseModel):
    """One Newton iteration's live snapshot (item 1 of the app rich-features
    brief): captured by ``app.engine.StageCapturingDiagnostics``, an app-side
    subclass of ``cins.diagnostics.recorder.NewtonDiagnostics`` (src/cins
    itself is never touched). Fed to the frontend Inverse Design Theater via
    the growing ``stages`` list on ``InverseResultPayload``, polled DURING the
    run (see ``app.jobs.run_job``'s ``on_progress`` wiring)."""

    it: int
    coords: list[list[float]] = Field(description="decimated airfoil outline, ~80 [x, y] pairs")
    cp_stations_x: list[float]
    cp_current: list[float]
    cp_target: list[float]
    alpha: float
    R_norm: float | None = None
    T_norm: float | None = None
    G_norm: float | None = None
    transition: dict[str, float] | None = None


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
    presolve_gate: dict[str, Any] | None = Field(
        None, description="raw_target mode only: realisability verdict, inviscid-consistent"
    )
    stages: list[InverseStage] = Field(
        default_factory=list,
        description="per-iteration live snapshots for the Theater view; grows during the run",
    )
    dof: dict[str, Any] | None = Field(
        None, description="DOF card: n_A_free (M), n_targets (M'), n_constraints (K), etc."
    )
    phase: str | None = Field(
        None,
        description=(
            "human-readable phase text (defect-fix: job hangs with no visible progress): "
            "e.g. 'fit: baseline CST fit', 'presolve pass 1/2', 'station selection', "
            "'initial solve', 'newton it 3'. Also mirrored job-level on InverseJobResponse.phase, "
            "which is the authoritative/most current value (updated even between progress calls)."
        ),
    )


class InverseJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    result: InverseResultPayload | None = None
    error: str | None = None
    phase: str = Field(
        "queued",
        description="current phase text: see InverseResultPayload.phase; authoritative source.",
    )
    created_at: float = Field(description="unix timestamp the job was created")
    updated_at: float = Field(description="unix timestamp of the last progress heartbeat")
    elapsed_s: float = Field(description="server-computed seconds since job creation")
    timeout_s: float = Field(
        description="server-side timeout (seconds) after which a still-running job is marked "
        "'error' with an explicit reason rather than hanging forever (CINS_INVERSE_TIMEOUT_S)"
    )


# --------------------------------------------------------------------------- #
# /api/inverse/raw: user-defined target Cp (product requirement: target
# editor / CSV import), reusing the same job store/poll endpoint as
# /api/inverse. Runs the T4 presolve realisability gate FIRST and always
# surfaces it, even when Newton itself is not attempted (dossier §7.10 guard
# made into product UX).
# --------------------------------------------------------------------------- #


class RawTargetSpec(BaseModel):
    """A user-defined target: either a raw Cp curve or a ue/Vinf curve (only
    valid for the incompressible baseline; converted server-side via
    Cp = 1 - (ue/Vinf)^2). Whole-loop ordering with a single x-minimum (LE);
    same convention as ``TargetCpSpec``."""

    x: list[float]
    cp: list[float] | None = None
    ue_over_vinf: list[float] | None = None

    @model_validator(mode="after")
    def _check(self) -> "RawTargetSpec":
        has_cp = self.cp is not None
        has_ue = self.ue_over_vinf is not None
        if has_cp == has_ue:
            raise ValueError("target needs exactly one of `cp` or `ue_over_vinf`")
        arr = self.cp if has_cp else self.ue_over_vinf
        if len(arr) != len(self.x):  # type: ignore[arg-type]
            raise ValueError("x and cp/ue_over_vinf must be the same length")
        if len(self.x) < 5:
            raise ValueError("target needs at least 5 stations")
        return self

    def to_cp(self) -> list[float]:
        if self.cp is not None:
            return self.cp
        return [1.0 - u * u for u in self.ue_over_vinf]  # type: ignore[union-attr]


class RawTargetInverseRequest(BaseModel):
    mode: Literal["raw_target"] = "raw_target"
    baseline: BaselineSpec
    target: RawTargetSpec
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    n: int = Field(8, ge=2, le=20, description="Bernstein order (only used for a `naca` baseline)")
    alpha_deg: float = Field(0.0, ge=-20.0, le=20.0, description="fixed alpha or alpha_free seed")
    alpha_free: bool = Field(
        True, description="absorbs an incidence offset; default on for arbitrary targets"
    )
    Re: float = Field(1.0e6, gt=1e3, lt=1e9)
    n_stations_offset: Literal[-1, 0, 1] = 0


class RawTargetGate(BaseModel):
    """The T4 presolve realisability verdict: always computed and returned,
    even on early failure, so the UI can show it before/instead of a Newton
    attempt (ADR-0004)."""

    realisability: float
    realisable: bool
    kkt_cond: float
    threshold: float
    A_upper_init: list[float]
    A_lower_init: list[float]
    screening: bool = Field(
        False,
        description="computed in the cheaper screening configuration "
        "(one presolve pass at the interactive paneling)",
    )
    npanel: int | None = Field(None, description="paneling the presolve ran at")
    presolve_passes: int | None = Field(None, description="presolve passes run")
    cached: bool = Field(False, description="served without recomputing")


class GateSubmitResponse(BaseModel):
    job_id: str
    status: str


class GateJobResponse(BaseModel):
    job_id: str
    status: str
    result: RawTargetGate | None = None
    error: str | None = None
    phase: str | None = None


class RawTargetSubmitResponse(BaseModel):
    job_id: str
    status: str


# --------------------------------------------------------------------------- #
# /api/showcase (item 7): archived T7 run + T8 panel table + paper figures
# --------------------------------------------------------------------------- #


class ShowcaseResponse(BaseModel):
    t7: dict[str, Any]
    panel: list[dict[str, Any]]
    panel_n_converged: int
    panel_n_total: int
    figures: list[str]
    gates: dict[str, Any] | None
    manifest_note: str
