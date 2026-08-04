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
}

export interface InverseJobResponse {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  result: InverseResultPayload | null;
  error: string | null;
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
