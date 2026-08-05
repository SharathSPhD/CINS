"use client";

import { useEffect, useRef, useState } from "react";
import TheaterStage from "@/components/TheaterStage";
import {
  airfoilGeometry,
  analyze,
  ApiError,
  pollInverse,
  presolveGateRaw,
  showcase,
  submitInverse,
  submitInverseRaw,
  type BaselineSpec,
  type DofAccounting,
  type InverseJobResponse,
  type RawTargetGate,
  type ShowcaseResponse,
} from "@/lib/api";

const POLL_INTERVAL_MS = 1500;

type Mode = "naca_target" | "raw_target";

export default function InversePage() {
  const [mode, setMode] = useState<Mode>("raw_target");

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Inverse Design Theater</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Submits a monolithic CST-Newton inverse solve (dossier §7.6) as a background job, then
        polls for status and animates every Newton iteration live — geometry, Cp vs target, and
        the R/T/G convergence trace — as they land.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-md border border-neutral-300 dark:border-neutral-700 overflow-hidden text-sm">
          <button
            className={`px-3 py-1.5 ${mode === "raw_target" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900" : ""}`}
            onClick={() => setMode("raw_target")}
          >
            Custom target
          </button>
          <button
            className={`px-3 py-1.5 ${mode === "naca_target" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900" : ""}`}
            onClick={() => setMode("naca_target")}
          >
            Self-consistency (NACA target)
          </button>
        </div>
        <ReplayArchivedT7 />
      </div>

      {mode === "naca_target" ? <NacaTargetPanel /> : <RawTargetPanel />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// "Replay archived T7" instant-demo button (item 7) — fed from the archived
// diagnostics.json residual series, NOT a live solve. Clearly labeled.
// --------------------------------------------------------------------------- //

function ReplayArchivedT7() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ShowcaseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onClick() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (data) return;
    setLoading(true);
    setError(null);
    try {
      setData(await showcase());
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={onClick}
        className="text-sm rounded-md border border-dashed border-neutral-400 dark:border-neutral-600 px-3 py-1.5"
      >
        {open ? "Hide" : "Replay archived T7 run"}
      </button>
      {open && (
        <div className="mt-3 rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400 mb-1">
            Archived replay — not a live solve
          </div>
          {loading && <div className="text-sm text-neutral-500">loading archived run...</div>}
          {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
          {data && (
            <>
              <p className="text-xs text-neutral-600 dark:text-neutral-400 mb-2">
                T7 self-consistency gate (NACA 2412, forced transition): recovers its own CST
                coefficients from its target Cp. Manifest:{" "}
                <code>{JSON.stringify(data.t7.manifest)}</code>
              </p>
              <ResidualChart history={(data.t7.residual_history.filter((v) => v != null) as number[])} />
              <div className="mt-2 text-xs font-mono whitespace-pre-wrap text-neutral-600 dark:text-neutral-400 max-h-40 overflow-auto">
                {data.t7.log_tail}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// naca_target mode (unchanged behavior from the previous single-mode page)
// --------------------------------------------------------------------------- //

function NacaTargetPanel() {
  const [airfoil, setAirfoil] = useState("2412");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<InverseJobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [targetCoords, setTargetCoords] = useState<number[][] | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setJob(null);
    try {
      const res = await submitInverse({ airfoil });
      setJobId(res.job_id);
      startPolling(res.job_id, setJob, setError, timerRef);
      airfoilGeometry(`naca:${airfoil}`)
        .then((g) => setTargetCoords(g.coords))
        .catch(() => setTargetCoords(null));
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-6">
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 text-sm text-neutral-600 dark:text-neutral-400">
        Runs a self-consistency inverse (recover a NACA airfoil&apos;s own CST coefficients from
        its target Cp, T7-style, forced transition, dossier default config) — a falsifiable check
        that the monolithic Newton system actually recovers a known answer.
      </div>

      <form onSubmit={onSubmit} className="mt-4 flex items-end gap-3">
        <label className="block">
          <span className="block text-xs font-medium text-neutral-600 dark:text-neutral-400 mb-1">
            Target NACA code
          </span>
          <input
            className="w-32 rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
            value={airfoil}
            onChange={(e) => setAirfoil(e.target.value)}
            maxLength={5}
          />
        </label>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {submitting ? "Submitting..." : "Run inverse solve"}
        </button>
      </form>

      {error && <ErrorBox message={error} />}
      {jobId && <JobStatus jobId={jobId} job={job} targetCoords={targetCoords} alphaFree={false} />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// raw_target mode — target editor (template-from-airfoil + table edit + CSV
// import), coordinate/baseline import, and the T4 realisability gate surfaced
// prominently BEFORE the Newton solve runs (product requirement: this is the
// dossier §7.10 guard made into UX).
// --------------------------------------------------------------------------- //

interface TargetPoint {
  x: number;
  cp: number;
}

function RawTargetPanel() {
  const [baselineMode, setBaselineMode] = useState<"naca" | "cst">("naca");
  const [baselineNaca, setBaselineNaca] = useState("0012");
  const [n, setN] = useState(8);

  const [templateNaca, setTemplateNaca] = useState("2412");
  const [templateAlpha, setTemplateAlpha] = useState(2.0);
  const [points, setPoints] = useState<TargetPoint[]>([]);
  const [csvUnits, setCsvUnits] = useState<"cp" | "ue">("cp");

  const [alphaDeg, setAlphaDeg] = useState(2.0);
  const [alphaFree, setAlphaFree] = useState(true);
  const [Re, setRe] = useState(1.0e6);

  const [useLeConstraint, setUseLeConstraint] = useState(false);
  const [rLe, setRLe] = useState(0.015);

  const [gate, setGate] = useState<RawTargetGate | null>(null);
  const [gateLoading, setGateLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<InverseJobResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  function buildBaseline(): BaselineSpec {
    return baselineMode === "naca" ? { naca: baselineNaca } : {};
  }

  async function loadTemplate() {
    setError(null);
    try {
      const res = await analyze({ naca: templateNaca, alpha: templateAlpha });
      const pts = res.x.map((x, i) => ({ x, cp: res.cp[i] }));
      setPoints(pts);
      setGate(null);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : String(err));
    }
  }

  function onCsvFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const text = String(reader.result ?? "");
        const rows = text
          .split(/\r?\n/)
          .map((l) => l.trim())
          .filter((l) => l.length > 0 && !/^[a-zA-Z]/.test(l));
        const parsed: TargetPoint[] = rows
          .map((row) => row.split(/[,\s]+/).map(Number))
          .filter((cols) => cols.length >= 2 && cols.every((v) => Number.isFinite(v)))
          .map(([x, val]) => ({ x, cp: csvUnits === "cp" ? val : 1 - val * val }));
        if (parsed.length < 5) {
          setError("CSV parsed to fewer than 5 valid (x, value) rows");
          return;
        }
        setPoints(parsed);
        setGate(null);
        setError(null);
      } catch (err) {
        setError(String(err));
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  }

  function updatePoint(i: number, field: "x" | "cp", value: number) {
    setPoints((prev) => prev.map((p, idx) => (idx === i ? { ...p, [field]: value } : p)));
  }

  function buildRawRequest() {
    return {
      baseline: buildBaseline(),
      target: { x: points.map((p) => p.x), cp: points.map((p) => p.cp) },
      constraints: useLeConstraint
        ? [{ type: "le_radius" as const, R_LE: rLe }]
        : [],
      n,
      alpha_deg: alphaDeg,
      alpha_free: alphaFree,
      Re,
    };
  }

  async function checkGate() {
    if (points.length < 5) {
      setError("Load or upload a target curve first (need >= 5 stations)");
      return;
    }
    setGateLoading(true);
    setError(null);
    try {
      const g = await presolveGateRaw(buildRawRequest());
      setGate(g);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : String(err));
    } finally {
      setGateLoading(false);
    }
  }

  async function onRunInverse() {
    if (points.length < 5) {
      setError("Load or upload a target curve first (need >= 5 stations)");
      return;
    }
    setSubmitting(true);
    setError(null);
    setJob(null);
    try {
      const res = await submitInverseRaw(buildRawRequest());
      setJobId(res.job_id);
      startPolling(res.job_id, setJob, setError, timerRef);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-6 grid gap-8 lg:grid-cols-[320px_1fr]">
      <div className="space-y-5">
        <Section title="1. Baseline geometry">
          <div className="flex gap-2 text-xs mb-2">
            <button
              className={`px-2 py-1 rounded border ${baselineMode === "naca" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900" : "border-neutral-300 dark:border-neutral-700"}`}
              onClick={() => setBaselineMode("naca")}
            >
              NACA code
            </button>
          </div>
          <Field label="NACA code">
            <input
              className={inputCls}
              value={baselineNaca}
              onChange={(e) => setBaselineNaca(e.target.value)}
              maxLength={5}
            />
          </Field>
          <Field label="Bernstein order n">
            <input
              type="number"
              min={2}
              max={20}
              className={inputCls}
              value={n}
              onChange={(e) => setN(Number(e.target.value))}
            />
          </Field>
        </Section>

        <Section title="2. Target pressure curve">
          <p className="text-xs text-neutral-500 mb-2">
            Start from an existing airfoil&apos;s Cp, then edit, or upload a CSV of
            (x/c, Cp) or (x/c, u_e/V&#8734;) rows.
          </p>
          <div className="flex items-end gap-2 mb-2">
            <Field label="Template airfoil (NACA)">
              <input
                className={inputCls}
                value={templateNaca}
                onChange={(e) => setTemplateNaca(e.target.value)}
                maxLength={5}
              />
            </Field>
            <Field label="alpha (deg)">
              <input
                type="number"
                step="0.1"
                className={inputCls}
                value={templateAlpha}
                onChange={(e) => setTemplateAlpha(Number(e.target.value))}
              />
            </Field>
          </div>
          <button
            type="button"
            onClick={loadTemplate}
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 py-1.5 text-sm"
          >
            Load as target template
          </button>

          <div className="mt-3 flex items-center gap-2 text-xs">
            <span>CSV column 2 is:</span>
            <select
              className="rounded border border-neutral-300 dark:border-neutral-700 bg-transparent px-1 py-0.5"
              value={csvUnits}
              onChange={(e) => setCsvUnits(e.target.value as "cp" | "ue")}
            >
              <option value="cp">Cp</option>
              <option value="ue">u_e / V&#8734; (incompressible: Cp = 1-(u_e/V&#8734;)^2)</option>
            </select>
          </div>
          <input type="file" accept=".csv,.txt" onChange={onCsvFile} className="mt-2 w-full text-xs" />

          {points.length > 0 && (
            <div className="mt-3 max-h-48 overflow-auto rounded border border-neutral-200 dark:border-neutral-800 text-xs">
              <table className="w-full">
                <thead className="sticky top-0 bg-neutral-100 dark:bg-neutral-900">
                  <tr>
                    <th className="text-left px-2 py-1">x/c</th>
                    <th className="text-left px-2 py-1">Cp</th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((p, i) => (
                    <tr key={i} className="odd:bg-neutral-50 dark:odd:bg-neutral-900/40">
                      <td>
                        <input
                          type="number"
                          step="0.001"
                          value={p.x}
                          onChange={(e) => updatePoint(i, "x", Number(e.target.value))}
                          className="w-full bg-transparent px-2 py-0.5"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          step="0.01"
                          value={p.cp}
                          onChange={(e) => updatePoint(i, "cp", Number(e.target.value))}
                          className="w-full bg-transparent px-2 py-0.5"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-1 text-xs text-neutral-500">{points.length} stations loaded</div>
        </Section>

        <Section title="3. Constraints (optional)">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={useLeConstraint}
              onChange={(e) => setUseLeConstraint(e.target.checked)}
            />
            Fix leading-edge radius
          </label>
          {useLeConstraint && (
            <Field label="R_LE (chords)">
              <input
                type="number"
                step="0.001"
                className={inputCls}
                value={rLe}
                onChange={(e) => setRLe(Number(e.target.value))}
              />
            </Field>
          )}
          <p className="mt-1 text-xs text-neutral-500">
            No explicit constraint added: the solver auto-adds a shared-LE-radius row
            target-consistent with the presolved initial guess (b = g&middot;A0), not an idealized
            value.
          </p>
        </Section>

        <Section title="4. Angle of attack">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={alphaFree}
              onChange={(e) => setAlphaFree(e.target.checked)}
            />
            alpha free (dossier FM-1 absorption DOF — recommended for arbitrary targets)
          </label>
          <Field label={alphaFree ? "alpha seed (deg)" : "alpha, fixed (deg)"}>
            <input
              type="number"
              step="0.1"
              className={inputCls}
              value={alphaDeg}
              onChange={(e) => setAlphaDeg(Number(e.target.value))}
            />
          </Field>
          <Field label="Reynolds number">
            <input
              type="number"
              step="1000"
              className={inputCls}
              value={Re}
              onChange={(e) => setRe(Number(e.target.value))}
            />
          </Field>
        </Section>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={checkGate}
            disabled={gateLoading}
            className="flex-1 rounded-md border border-neutral-300 dark:border-neutral-700 py-2 text-sm font-medium disabled:opacity-50"
          >
            {gateLoading ? "Checking..." : "Check realisability"}
          </button>
          <button
            type="button"
            onClick={onRunInverse}
            disabled={submitting}
            className="flex-1 rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 py-2 text-sm font-medium disabled:opacity-50"
          >
            {submitting ? "Submitting..." : "Run inverse solve"}
          </button>
        </div>

        {error && <ErrorBox message={error} />}
      </div>

      <div className="space-y-6">
        {gate && <GateCard gate={gate} />}
        {jobId && <JobStatus jobId={jobId} job={job} alphaFree={alphaFree} />}
        {!gate && !jobId && (
          <div className="text-sm text-neutral-500 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-8 text-center">
            Load a target curve, then check realisability or run the inverse solve.
          </div>
        )}
      </div>
    </div>
  );
}

function GateCard({ gate }: { gate: RawTargetGate }) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        gate.realisable
          ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30"
          : "border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30"
      }`}
    >
      <h2 className="text-sm font-medium">
        T4 realisability gate: {gate.realisable ? "realisable" : "WARNING — may be outside the CST manifold"}
      </h2>
      <p className="mt-1 text-xs text-neutral-600 dark:text-neutral-400">
        ||M &middot; &Delta;A - (Cp_target - Cp0)|| / ||Cp_target|| = {gate.realisability.toFixed(4)} (threshold{" "}
        {gate.threshold}). {gate.realisable
          ? "The target is within the CST-representable manifold at this baseline — Newton should converge normally."
          : "This target may not be representable by this CST parameterization/order; the monolithic Newton solve may stagnate or fail to converge. You can still proceed."}
      </p>
      <p className="mt-1 text-xs text-neutral-500">KKT condition number: {gate.kkt_cond.toExponential(2)}</p>
    </div>
  );
}

function startPolling(
  jobId: string,
  setJob: (j: InverseJobResponse) => void,
  setError: (e: string) => void,
  timerRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>,
) {
  if (timerRef.current) clearInterval(timerRef.current);
  timerRef.current = setInterval(async () => {
    try {
      const j = await pollInverse(jobId);
      setJob(j);
      if (j.status === "done" || j.status === "error") {
        if (timerRef.current) clearInterval(timerRef.current);
      }
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : String(err));
      if (timerRef.current) clearInterval(timerRef.current);
    }
  }, POLL_INTERVAL_MS);
}

function JobStatus({
  jobId,
  job,
  targetCoords,
  alphaFree,
}: {
  jobId: string;
  job: InverseJobResponse | null;
  targetCoords?: number[][] | null;
  alphaFree?: boolean;
}) {
  const stages = job?.result?.stages ?? [];
  const dof: DofAccounting | null | undefined = job?.result?.dof;
  const gate = job?.result?.presolve_gate as RawTargetGate | undefined;
  const rv = job?.result?.release_verify as
    | { cl?: number; cl_target?: number; dcl?: number; cd?: number; cd_target?: number; dcd?: number; converged?: boolean; ok?: boolean; note?: string }
    | null
    | undefined;

  return (
    <div className="space-y-4">
      <div className="text-sm text-neutral-600 dark:text-neutral-400">
        job <code>{jobId}</code> — status: <span className="font-mono">{job?.status ?? "queued"}</span>
        {job?.status === "running" && stages.length > 0 && (
          <span className="ml-2 text-neutral-500">({stages.length} Newton iterations so far)</span>
        )}
      </div>

      {gate && <GateCard gate={gate} />}

      {stages.length > 0 ? (
        <TheaterStage stages={stages} targetCoords={targetCoords} dof={dof} alphaFree={alphaFree} />
      ) : (
        <div className="text-sm text-neutral-500 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-6 text-center">
          Presolving / waiting for the first Newton iteration...
        </div>
      )}

      {job?.status === "error" && <ErrorBox message={job.error ?? "unknown error"} />}

      {job?.status === "done" && job.result?.dof_check_error && (
        <ErrorBox message={`DOF check failed: ${job.result.dof_check_error}`} />
      )}

      {job?.status === "done" && (
        <div
          className={`rounded-lg border p-4 ${
            job.result?.converged
              ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30"
              : "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40"
          }`}
        >
          <h2 className="text-sm font-medium mb-2">
            Verdict: {job.result?.converged ? "converged" : "did not converge"}
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="iterations" value={String(job.result?.iterations ?? "—")} />
            <Stat label="alpha (deg)" value={job.result?.alpha?.toFixed(3) ?? "—"} />
            <Stat
              label="convergence order"
              value={job.result?.convergence_order?.toFixed(2) ?? "—"}
            />
            <Stat label="realisability" value={job.result?.realisability?.toFixed(4) ?? "—"} />
          </div>
          {rv && (
            <div className="mt-3 text-xs text-neutral-600 dark:text-neutral-400">
              <div className="font-medium mb-1">
                release-verify: {rv.ok === undefined ? (rv.converged ? "converged" : "?") : rv.ok ? "PASS" : "FAIL"}
              </div>
              {rv.cl !== undefined && (
                <div className="font-mono">
                  cl={rv.cl.toFixed(4)}
                  {rv.cl_target !== undefined && ` (target ${rv.cl_target.toFixed(4)}, d=${rv.dcl?.toExponential(1)})`}
                  {"  "}
                  cd={rv.cd?.toFixed(5)}
                  {rv.cd_target !== undefined && ` (target ${rv.cd_target.toFixed(5)}, d=${rv.dcd?.toExponential(1)})`}
                </div>
              )}
              {rv.note && <div className="mt-1 text-neutral-500">{rv.note}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block mb-2">
      <span className="block text-xs font-medium text-neutral-600 dark:text-neutral-400 mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-2">
        {title}
      </h3>
      {children}
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
      {message}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-lg font-mono">{value}</div>
    </div>
  );
}

function ResidualChart({ history }: { history: number[] }) {
  const width = 560;
  const height = 220;
  const margin = { top: 10, right: 10, bottom: 24, left: 40 };
  const logs = history.map((v) => Math.log10(Math.max(v, 1e-16)));
  const yMin = Math.min(...logs);
  const yMax = Math.max(...logs);
  const span = yMax - yMin || 1;

  const sx = (i: number) =>
    margin.left + (history.length <= 1 ? 0 : (i / (history.length - 1)) * (width - margin.left - margin.right));
  const sy = (v: number) =>
    margin.top + (1 - (v - yMin) / span) * (height - margin.top - margin.bottom);

  const path = logs.map((v, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(2)},${sy(v).toFixed(2)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto text-neutral-400 dark:text-neutral-600">
      <line
        x1={margin.left}
        x2={width - margin.right}
        y1={height - margin.bottom}
        y2={height - margin.bottom}
        stroke="currentColor"
      />
      <line x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} stroke="currentColor" />
      <path d={path} fill="none" stroke="#3b82f6" strokeWidth={2} />
      {logs.map((v, i) => (
        <circle key={i} cx={sx(i)} cy={sy(v)} r={3} fill="#3b82f6" />
      ))}
      <text x={margin.left} y={height - 4} fontSize={11} className="fill-neutral-500 dark:fill-neutral-400">
        iteration
      </text>
      <text x={4} y={margin.top + 8} fontSize={11} className="fill-neutral-500 dark:fill-neutral-400">
        log10‖R‖
      </text>
    </svg>
  );
}
