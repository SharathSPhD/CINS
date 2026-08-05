// Typed client for the CINS FastAPI backend, called through Next's /api
// rewrite proxy (see next.config.ts) so the browser only ever talks to the
// same origin it's served from. Mirrors app/backend/app/schemas.py.

export interface SurfaceCp {
  x: number[];
  cp: number[];
}

export interface TransitionSpec {
  mode: "forced" | "free";
  xtr_upper: number;
  xtr_lower: number;
}

export interface AnalyzeRequest {
  naca?: string;
  coords?: number[][];
  alpha: number;
  Re?: number;
  Ma?: number;
  transition?: TransitionSpec;
}

export interface AnalyzeResponse {
  converged: boolean;
  cl: number;
  cd: number;
  cm: number;
  alpha: number;
  Re: number | null;
  Ma: number;
  x: number[];
  cp: number[];
  upper: SurfaceCp;
  lower: SurfaceCp;
  coords: number[][];
}

export interface InverseRequest {
  mode?: "naca_target";
  airfoil: string;
  alpha_deg?: number;
  Re?: number;
  Ma?: number;
  n_upper?: number;
  n_lower?: number;
  le_treatment?: "none" | "lem" | "prescribed";
  transition_mode?: "forced" | "free";
  alpha_free?: boolean;
  station_selection?: "qr_pivot" | "even";
  init?: "presolve" | "perturbed" | "random";
  dof_offset?: -1 | 0 | 1;
}

export interface InverseSubmitResponse {
  job_id: string;
  status: string;
}

export interface ReleaseVerify {
  cl: number;
  cl_target: number;
  dcl: number;
  cd: number;
  cd_target: number;
  dcd: number;
  converged: boolean;
  ok: boolean;
}

export interface IterationDiag {
  it: number;
  R_norm: number;
  T_norm: number;
  G_norm: number;
  rank_J: number | null;
  cond_J: number | null;
  omega: number | null;
  dA_norm: number | null;
}

export interface InverseResultPayload {
  converged: boolean;
  iterations: number;
  alpha: number | null;
  A_upper: number[] | null;
  A_lower: number[] | null;
  coords: number[][] | null;
  residual_history: number[];
  convergence_order: number | null;
  release_verify: ReleaseVerify | null;
  realisability: number | null;
  model_gap: number | null;
  submap_cond: number | null;
  notes: string[];
  dof_check_error: string | null;
  wall_time_s: number;
  diagnostics: IterationDiag[];
  manifest: Record<string, unknown> | null;
  presolve_gate?: Record<string, unknown> | null;
}

export interface InverseJobResponse {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  result: InverseResultPayload | null;
  error: string | null;
}

// --------------------------------------------------------------------------- //
// /api/fit derived quantities, /api/airfoils, /api/geometry/from-cst
// --------------------------------------------------------------------------- //

export interface DerivedGeometry {
  le_radius: number;
  te_wedge_upper_deg: number;
  te_wedge_lower_deg: number;
  te_gap: number;
  max_thickness: number;
  max_thickness_x: number;
  max_camber: number;
  max_camber_x: number;
  area: number;
}

export interface FitRequest {
  coords: number[][];
  n?: number;
  N1?: number;
  N2?: number;
  te_gap?: number | null;
}

export interface FitResponse {
  A_upper: number[];
  A_lower: number[];
  zeta_T_upper: number;
  zeta_T_lower: number;
  n: number;
  N1: number;
  N2: number;
  rms: number;
  gram_condition: number;
  derived: DerivedGeometry;
}

export interface AirfoilListItem {
  id: string;
  name: string;
  source: "uiuc" | "naca";
  thickness: number | null;
  camber: number | null;
  n_points: number | null;
}

export interface AirfoilListResponse {
  uiuc: AirfoilListItem[];
  naca: AirfoilListItem[];
}

export interface AirfoilGeometryResponse {
  id: string;
  coords: number[][];
}

export interface GeometryFromCSTRequest {
  A_upper: number[];
  A_lower: number[];
  zeta_T_upper?: number;
  zeta_T_lower?: number;
  N1?: number;
  N2?: number;
  npoint?: number;
}

export interface GeometryFromCSTResponse {
  coords: number[][];
  derived: DerivedGeometry;
}

export function fit(req: FitRequest): Promise<FitResponse> {
  return postJson("/api/fit", req);
}

export function listAirfoils(): Promise<AirfoilListResponse> {
  return getJson("/api/airfoils");
}

export function airfoilGeometry(id: string): Promise<AirfoilGeometryResponse> {
  return getJson(`/api/airfoils/${encodeURIComponent(id)}/geometry`);
}

export function geometryFromCst(req: GeometryFromCSTRequest): Promise<GeometryFromCSTResponse> {
  return postJson("/api/geometry/from-cst", req);
}

// --------------------------------------------------------------------------- //
// /api/flowfield
// --------------------------------------------------------------------------- //

export interface FlowFieldGrid {
  nx?: number;
  ny?: number;
  x_min?: number;
  x_max?: number;
  y_min?: number;
  y_max?: number;
}

export interface FlowFieldRequest {
  naca?: string;
  coords?: number[][];
  alpha: number;
  Ma?: number;
  grid?: FlowFieldGrid;
}

export interface FlowFieldResponse {
  x: number[];
  y: number[];
  u: (number | null)[][];
  v: (number | null)[][];
  speed: (number | null)[][];
  cp: (number | null)[][];
  airfoil: number[][];
  alpha: number;
  Vinf: number;
  nx: number;
  ny: number;
  note: string;
}

export function flowfield(req: FlowFieldRequest): Promise<FlowFieldResponse> {
  return postJson("/api/flowfield", req);
}

// --------------------------------------------------------------------------- //
// /api/inverse/raw, /api/inverse/gate — user-defined target Cp
// --------------------------------------------------------------------------- //

export interface BaselineSpec {
  naca?: string;
  A_upper?: number[];
  A_lower?: number[];
  zeta_T_upper?: number;
  zeta_T_lower?: number;
}

export interface RawTargetSpec {
  x: number[];
  cp?: number[];
  ue_over_vinf?: number[];
}

export interface ConstraintSpec {
  type: "shared_le_radius" | "le_radius" | "te_wedge" | "area";
  R_LE?: number;
  beta?: number;
  dz_TE?: number;
  side?: "upper" | "lower";
  target_area?: number;
}

export interface RawTargetInverseRequest {
  mode?: "raw_target";
  baseline: BaselineSpec;
  target: RawTargetSpec;
  constraints?: ConstraintSpec[];
  n?: number;
  alpha_deg?: number;
  alpha_free?: boolean;
  Re?: number;
  n_stations_offset?: -1 | 0 | 1;
}

export interface RawTargetGate {
  realisability: number;
  realisable: boolean;
  kkt_cond: number;
  threshold: number;
  A_upper_init: number[];
  A_lower_init: number[];
}

export function presolveGateRaw(req: RawTargetInverseRequest): Promise<RawTargetGate> {
  return postJson("/api/inverse/gate", req);
}

export function submitInverseRaw(req: RawTargetInverseRequest): Promise<InverseSubmitResponse> {
  return postJson("/api/inverse/raw", req);
}

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

async function postJson<TReq, TRes>(path: string, body: TReq): Promise<TRes> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => res.statusText);
    throw new ApiError(res.status, detail.detail ?? detail);
  }
  return res.json() as Promise<TRes>;
}

async function getJson<TRes>(path: string): Promise<TRes> {
  const res = await fetch(path);
  if (!res.ok) {
    const detail = await res.json().catch(() => res.statusText);
    throw new ApiError(res.status, detail.detail ?? detail);
  }
  return res.json() as Promise<TRes>;
}

export function analyze(req: AnalyzeRequest): Promise<AnalyzeResponse> {
  return postJson("/api/analyze", req);
}

export function submitInverse(req: InverseRequest): Promise<InverseSubmitResponse> {
  return postJson("/api/inverse", req);
}

export function pollInverse(jobId: string): Promise<InverseJobResponse> {
  return getJson(`/api/inverse/${jobId}`);
}

export { ApiError };
