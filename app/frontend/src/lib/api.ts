// Typed client for the CINS FastAPI backend. Mirrors app/backend/app/schemas.py.
//
// Origin strategy: when NEXT_PUBLIC_API_BASE is set (public deploys), the
// browser calls the backend origin DIRECTLY: Vercel's rewrite proxy caps
// long requests, and a viscous solve on the free-tier backend can take
// minutes (measured 166s cold); direct browser fetch has no such cap and the
// backend's CORS allows it. Locally (env unset) requests stay same-origin
// and go through Next's /api rewrite (see next.config.ts).
const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE ?? "";

function apiUrl(path: string): string {
  return `${API_ORIGIN}${path}`;
}

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

export interface SurfaceSplit {
  upper: number[];
  lower: number[];
}

export interface BLDistributions {
  x: SurfaceSplit;
  theta: SurfaceSplit;
  delta_star: SurfaceSplit;
  cf: SurfaceSplit;
  Hk: SurfaceSplit;
  amplification: SurfaceSplit;
  ue: SurfaceSplit;
  uei: SurfaceSplit;
  Re_theta: SurfaceSplit;
  transition_x: { upper: number; lower: number } | null;
}

export interface AnalyzeResponse {
  converged: boolean;
  cl: number;
  cd: number;
  cm: number;
  cdf: number | null;
  cdp: number | null;
  alpha: number;
  Re: number | null;
  Ma: number;
  x: number[];
  cp: number[];
  upper: SurfaceCp;
  lower: SurfaceCp;
  upper_cpi: SurfaceCp | null;
  lower_cpi: SurfaceCp | null;
  sonic_cp: number | null;
  coords: number[][];
  bl: BLDistributions | null;
  bl_offset: { upper: number[][]; lower: number[][] } | null;
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

export interface InverseStage {
  it: number;
  coords: number[][];
  cp_stations_x: number[];
  cp_current: number[];
  cp_target: number[];
  alpha: number;
  R_norm: number | null;
  T_norm: number | null;
  G_norm: number | null;
  transition: { upper: number; lower: number } | null;
}

export interface DofAccounting {
  n_A_free: number;
  M: number;
  K: number;
  squareness_residual: number;
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
  stages: InverseStage[];
  dof: DofAccounting | null;
  phase: string | null;
}

export interface InverseJobResponse {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  result: InverseResultPayload | null;
  error: string | null;
  /** Authoritative current-phase text: see app/backend/app/jobs.py. */
  phase: string;
  created_at: number;
  updated_at: number;
  /** Server-computed seconds since submission: drives the elapsed/heartbeat UI. */
  elapsed_s: number;
  /** Server-side watchdog budget (seconds); job is marked "error" past this. */
  timeout_s: number;
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

// The backend evaluates the whole grid with a vectorized numpy evaluator
// (app/backend/app/flowfield.py) rather than one vendor Python call per grid
// point: measured ~0.3-0.7s locally even at the largest grid the backend
// will accept (engine._FLOWFIELD_MAX_CELLS), versus 100s+ before
// vectorizing. 30s gives ~3x margin over the ~8-10s worst case estimated for
// the Render free tier (roughly 20x slower than local) plus room for a
// free-tier cold start, without reintroducing the old "stuck at 90s" wait.
// The free-tier backend takes ~8.5 s for the default grid, roughly 20x
// local. 30 s sat on that boundary and tripped every time.
const FLOWFIELD_TIMEOUT_MS = 90_000;

export function flowfield(req: FlowFieldRequest): Promise<FlowFieldResponse> {
  return postJson("/api/flowfield", req, FLOWFIELD_TIMEOUT_MS);
}

export interface FlowFieldSubmitResponse {
  job_id: string;
  status: string;
}

export interface FlowFieldJobResponse {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  result: FlowFieldResponse | null;
  error: string | null;
  phase: string | null;
}

export function submitFlowField(req: FlowFieldRequest): Promise<FlowFieldSubmitResponse> {
  return postJson("/api/flowfield/submit", req, DEFAULT_TIMEOUT_MS);
}

export function pollFlowField(jobId: string): Promise<FlowFieldJobResponse> {
  return getJson(`/api/flowfield/${jobId}`, DEFAULT_TIMEOUT_MS);
}

/**
 * Submit the field and poll it to completion. The default 60x40 grid measures
 * 92.3s on the deployed free-tier container against the 90s the synchronous
 * call allowed, so it failed on the margin rather than on the request. Polling
 * removes the margin entirely.
 */
export async function flowFieldViaJob(
  req: FlowFieldRequest,
  onPhase?: (phase: string) => void,
  pollMs = 1500,
): Promise<FlowFieldResponse> {
  const { job_id } = await submitFlowField(req);
  for (;;) {
    const job = await pollFlowField(job_id);
    if (job.phase && onPhase) onPhase(job.phase);
    if (job.status === "done" && job.result) return job.result;
    if (job.status === "error") throw new ApiError(400, job.error ?? "flow field failed");
    await new Promise((r) => setTimeout(r, pollMs));
  }
}

// --------------------------------------------------------------------------- //
// /api/inverse/raw, /api/inverse/gate: user-defined target Cp
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
  screening?: boolean;
  npanel?: number | null;
  presolve_passes?: number | null;
  cached?: boolean;
}

// The gate spends two inviscid solves per CST coefficient, so at order 6 it is
// 15 solves in the screening configuration and 60 at full fidelity. Measured
// against the deployed backend, the full-fidelity form did not return within
// 600s, so the previous 120s budget was not merely too small: no fixed budget
// works. The job form below is the supported path; this one stays for scripted
// callers and for the cache hit, which is immediate.
const GATE_TIMEOUT_MS = 120_000;

export function presolveGateRaw(req: RawTargetInverseRequest): Promise<RawTargetGate> {
  return postJson("/api/inverse/gate", req, GATE_TIMEOUT_MS);
}

export interface GateSubmitResponse {
  job_id: string;
  status: string;
}

export interface GateJobResponse {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  result: RawTargetGate | null;
  error: string | null;
  phase: string | null;
}

export function submitPresolveGate(req: RawTargetInverseRequest): Promise<GateSubmitResponse> {
  return postJson("/api/inverse/gate/submit", req, DEFAULT_TIMEOUT_MS);
}

export function pollPresolveGate(jobId: string): Promise<GateJobResponse> {
  return getJson(`/api/inverse/gate/${jobId}`, DEFAULT_TIMEOUT_MS);
}

/**
 * Submit the realisability gate and poll it to completion. Each request is
 * short, so no single call can time out however slow the container is.
 */
export async function presolveGateViaJob(
  req: RawTargetInverseRequest,
  onPhase?: (phase: string) => void,
  pollMs = 2000,
): Promise<RawTargetGate> {
  const { job_id } = await submitPresolveGate(req);
  for (;;) {
    const job = await pollPresolveGate(job_id);
    if (job.phase && onPhase) onPhase(job.phase);
    if (job.status === "done" && job.result) return job.result;
    if (job.status === "error") throw new ApiError(400, job.error ?? "gate failed");
    await new Promise((r) => setTimeout(r, pollMs));
  }
}

export function submitInverseRaw(req: RawTargetInverseRequest): Promise<InverseSubmitResponse> {
  return postJson("/api/inverse/raw", req);
}

// --------------------------------------------------------------------------- //
// /api/airfoils/upload
// --------------------------------------------------------------------------- //

export interface AirfoilUploadResponse {
  id: string;
  name: string;
  coords: number[][];
  n_points: number;
  fit: FitResponse;
}

export async function uploadAirfoil(file: File): Promise<AirfoilUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(apiUrl("/api/airfoils/upload"), { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.json().catch(() => res.statusText);
    throw new ApiError(res.status, detail.detail ?? detail);
  }
  return res.json() as Promise<AirfoilUploadResponse>;
}

// --------------------------------------------------------------------------- //
// /api/showcase
// --------------------------------------------------------------------------- //

export interface ShowcaseT7 {
  manifest: Record<string, unknown> | null;
  convergence_order: number | null;
  residual_history: (number | null)[];
  iterations: Record<string, unknown>[];
  log_tail: string;
}

export interface ShowcasePanelEntry {
  cell_name: string;
  converged: boolean | null;
  iterations: number | null;
  err_all_inf: number | null;
  wall_time_s: number | null;
  notes: string[];
  airfoil_id: string | null;
}

export interface ShowcaseResponse {
  t7: ShowcaseT7;
  panel: ShowcasePanelEntry[];
  panel_n_converged: number;
  panel_n_total: number;
  figures: string[];
  gates: Record<string, unknown> | null;
  manifest_note: string;
}

// The Gallery shows archived results only, so this needs no backend. Reading
// the pre-generated asset first (scripts/gen_showcase.py, kept in step with
// GET /api/showcase because it is produced by the same run_showcase) means a
// cold free-tier container no longer leaves the page on "Loading archived
// results..." for the length of a spin-up. The endpoint stays as the fallback
// so a deployment without the asset still works.
export async function showcase(): Promise<ShowcaseResponse> {
  try {
    const res = await fetchWithTimeout("/showcase.json", {}, 8000);
    if (res.ok) return (await res.json()) as ShowcaseResponse;
  } catch {
    // fall through to the API
  }
  return getJson("/api/showcase");
}

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

// Default client-side request timeout. The failure mode this guards against
// (defect-fix: Flow Field / Analyze showing "Solving..." with no solution
// ever appearing) is a request that never resolves: a dropped connection,
// a proxy that holds the socket open past its own server-side timeout, or a
// free-tier backend cold-start (app/README.md: ~166s for a viscous analyze
// on Render's 0.1-vCPU instance): NOT a fast 4xx/5xx, which fetch() already
// rejects promptly. Without this, `loading` state has no way to ever clear.
const DEFAULT_TIMEOUT_MS = 45_000;

class TimeoutError extends Error {
  constructor(ms: number) {
    super(`request timed out after ${(ms / 1000).toFixed(0)}s`);
  }
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new TimeoutError(timeoutMs);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function postJson<TReq, TRes>(
  path: string,
  body: TReq,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<TRes> {
  const res = await fetchWithTimeout(
    apiUrl(path),
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    timeoutMs,
  );
  if (!res.ok) {
    const detail = await res.json().catch(() => res.statusText);
    throw new ApiError(res.status, detail.detail ?? detail);
  }
  return res.json() as Promise<TRes>;
}

async function getJson<TRes>(path: string, timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<TRes> {
  const res = await fetchWithTimeout(apiUrl(path), {}, timeoutMs);
  if (!res.ok) {
    const detail = await res.json().catch(() => res.statusText);
    throw new ApiError(res.status, detail.detail ?? detail);
  }
  return res.json() as Promise<TRes>;
}

// Analyze can run a full viscous mfoil solve whenever Re is given (the
// Analyze page prefills Re=1e6, so this is the DEFAULT path, not an edge
// case). Measured directly against the deployed Render free-tier backend,
// warm, back to back: a viscous NACA 2412 analyze took 124s on one run and
// 192s on another (the free instance's 0.1 vCPU is shared/throttled, so wall
// time varies run to run); app/README.md separately documents ~166s on a
// cold container. The old DEFAULT_TIMEOUT_MS (45s) aborted every such
// request client-side well before the backend could ever finish, which is
// the defect this fixes (not a dropped connection: the backend was always
// going to answer, just slower than the client allowed it to). 240s keeps
// real margin above the 192s worst case actually observed, not just the
// documented one. Inviscid analyze (no Re) stays fast (~16s measured) and
// finishes well inside this budget either way.
const ANALYZE_TIMEOUT_MS = 240_000;

export function analyze(req: AnalyzeRequest): Promise<AnalyzeResponse> {
  return postJson("/api/analyze", req, ANALYZE_TIMEOUT_MS);
}

// Preferred path for the Analyze page. Raising the timeout above only widened
// the window the request had to finish inside; it did not remove the window,
// so a slow container still surfaced as an error rather than as a wait. The
// job form has no window at all: the solve is started, the connection is
// released, and the answer is collected by polling. The only budget left is
// the user's patience, which the caller controls via onPhase.
export interface AnalyzeSubmitResponse {
  job_id: string;
  status: string;
}

export interface AnalyzeJobResponse {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  result: AnalyzeResponse | null;
  error: string | null;
  phase: string | null;
}

export function submitAnalyze(req: AnalyzeRequest): Promise<AnalyzeSubmitResponse> {
  return postJson("/api/analyze/submit", req, DEFAULT_TIMEOUT_MS);
}

export function pollAnalyze(jobId: string): Promise<AnalyzeJobResponse> {
  return getJson(`/api/analyze/${jobId}`, DEFAULT_TIMEOUT_MS);
}

/**
 * Submit an analyze and poll it to completion. Each individual request is
 * short, so no single call can time out however slow the container is.
 * `onPhase` reports what the backend says it is doing, so the wait shows
 * movement rather than a bare spinner.
 */
export async function analyzeViaJob(
  req: AnalyzeRequest,
  onPhase?: (phase: string) => void,
  pollMs = 1500,
): Promise<AnalyzeResponse> {
  const { job_id } = await submitAnalyze(req);
  for (;;) {
    const job = await pollAnalyze(job_id);
    if (job.phase && onPhase) onPhase(job.phase);
    if (job.status === "done" && job.result) return job.result;
    if (job.status === "error") throw new ApiError(400, job.error ?? "analyze failed");
    await new Promise((r) => setTimeout(r, pollMs));
  }
}

// Cheap liveness probe (app/backend/app/routers/health.py's GET /health,
// proxied locally by next.config.ts's rewrite). Used to ping the backend on
// page load so a free-tier cold start begins spinning up BEFORE the user
// clicks Solve, and to detect "the container is asleep" so the UI can say so
// instead of just showing a spinner for a while.
export interface HealthResponse {
  status: string;
}

const HEALTH_TIMEOUT_MS = 20_000; // generous: this call IS the cold-start wake-up

export function health(): Promise<HealthResponse> {
  return getJson("/health", HEALTH_TIMEOUT_MS);
}

export function submitInverse(req: InverseRequest): Promise<InverseSubmitResponse> {
  return postJson("/api/inverse", req);
}

export function pollInverse(jobId: string): Promise<InverseJobResponse> {
  return getJson(`/api/inverse/${jobId}`);
}

export { ApiError, TimeoutError };

/** Formats any error thrown by this module into user-facing text. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) return String(err.detail);
  if (err instanceof TimeoutError) return err.message;
  return String(err);
}
