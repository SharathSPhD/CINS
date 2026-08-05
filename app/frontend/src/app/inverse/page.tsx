"use client";

import ArchivedResidualChart from "@/components/ArchivedResidualChart";

import { useEffect, useRef, useState } from "react";
import AirfoilShape from "@/components/AirfoilShape";
import CstPanel from "@/components/CstPanel";
import TheaterStage from "@/components/TheaterStage";
import {
  airfoilGeometry,
  analyze,
  describeError,
  pollInverse,
  presolveGateRaw,
  showcase,
  submitInverse,
  submitInverseRaw,
  type BaselineSpec,
  type DofAccounting,
  type InverseJobResponse,
  type InverseResultPayload,
  type RawTargetGate,
  type ShowcaseResponse,
} from "@/lib/api";
import { loadCorpus, type CorpusAirfoil } from "@/lib/corpus";

const POLL_INTERVAL_MS = 1500;

type Mode = "naca_target" | "raw_target";

export default function InversePage() {
  const [mode, setMode] = useState<Mode>("raw_target");

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Inverse Design Theater</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Submits a monolithic CST-Newton inverse solve (dossier §7.6) as a background job, then
        polls for status and animates every Newton iteration live: geometry, Cp vs target, and
        the R/T/G convergence trace: as they land.
      </p>

      <div className="mt-4 inline-flex rounded-md border border-neutral-300 dark:border-neutral-700 overflow-hidden text-sm">
        <button
          className={`px-3 py-1.5 ${mode === "raw_target" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900": ""}`}
          onClick={() => setMode("raw_target")}
        >
          Custom target
        </button>
        <button
          className={`px-3 py-1.5 ${mode === "naca_target" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900": ""}`}
          onClick={() => setMode("naca_target")}
        >
          Self-consistency (NACA target)
        </button>
      </div>

      {/* Both panels stay mounted and are shown/hidden with CSS rather than
          conditionally rendered: defect-fix: switching tabs used to UNMOUNT
          the inactive panel, silently wiping its local state (loaded target
          points, the realisability gate, an in-flight job) so a user who
          glanced at the other tab and came back saw "Load or upload a target
          curve first" even though they HAD loaded one. See RawTargetPanel's
          own `points` state below. */}
      <div style={{ display : mode === "raw_target" ? "block" : "none" }}>
        <RawTargetPanel />
      </div>
      <div style={{ display : mode === "naca_target" ? "block" : "none" }}>
        <NacaTargetPanel />
      </div>

      {/* Archived reference material, not a live solve: deliberately placed
          BELOW the live Theater so the primary visuals (this run's geometry
          evolution, Cp vs target, convergence) lead and the archived replay
          is a supporting reference, not the first thing on the page. */}
      <ReplayArchivedT7 />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// "Replay archived T7" instant-demo button (item 7): fed from the archived
// diagnostics.json residual series, NOT a live solve. Clearly labeled.
// --------------------------------------------------------------------------- //

function ReplayArchivedT7() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ShowcaseResponse | null>(null);
  const [targetCoords, setTargetCoords] = useState<number[][] | null>(null);
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
      airfoilGeometry("naca:2412")
        .then((g) => setTargetCoords(g.coords))
        .catch(() => setTargetCoords(null));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }

  const iters = data?.t7.iterations as
    | { it: number; R_norm: number | null; T_norm: number | null; G_norm: number | null }[]
    | undefined;
  const nIters = iters?.length ?? data?.t7.residual_history.length ?? 0;
  const order = data?.t7.convergence_order;

  return (
    <section className="mt-14 border-t border-neutral-200 dark:border-neutral-800 pt-6">
      <button
        type="button"
        onClick={onClick}
        className="text-sm rounded-md border border-dashed border-neutral-400 dark:border-neutral-600 px-3 py-1.5 text-neutral-600 dark:text-neutral-400"
      >
        {open ? "Hide archived reference run" : "Show archived reference run (T7 self-consistency)"}
      </button>
      {open && (
        <div className="mt-3 rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
            Archived replay: not a live solve
          </div>
          {loading && <div className="text-sm text-neutral-500">loading archived run...</div>}
          {error && <ErrorBox message={error} />}
          {data && (
            <>
              <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">
                What this is: a NACA 2412 airfoil (forced transition, prescribed leading edge) run
                through the monolithic Newton solve with its OWN Cp as the target: a
                self-consistency check, not a demo of drawing an arbitrary target. What to look
                for: the combined residual (flow + target-Cp + constraint rows, {"‖(R,T,G)‖"})
                collapses from O(10&#8315;&#179;) toward machine precision (~10&#8315;&#185;&#8304;) in{" "}
                {nIters} iterations: the quadratic (Newton) convergence rate the dossier predicts
                for a square, well-conditioned system, not a slow asymptotic crawl.
              </p>
              {iters && iters.length > 0 ? (
                <ArchivedResidualChart iterations={iters} />
              ): (
                <ResidualChart history={(data.t7.residual_history.filter((v) => v != null) as number[])} />
              )}
              <div className="mt-3 grid gap-4 sm:grid-cols-[1fr_auto] items-start">
                <div className="text-xs text-neutral-500">
                  R (flow) convergence-order estimate, log-log slope over the final 3 iterations:{" "}
                  <span className="font-mono">{order?.toFixed(3) ?? ","}</span>. Read this
                  alongside the chart above, not instead of it: R was already at 10&#8315;&#185;&#178;
                  by iteration 0 in this run (a near-converged initial guess), so this estimator is
                  measuring floating-point noise at the residual floor, not the asymptotic rate: a value far from 2 here does not mean slow convergence. The collapse driving this
                  run is the target-Cp residual (T, orange above), not R.
                </div>
              </div>
              {targetCoords && (
                <div className="mt-4">
                  <div className="text-xs font-medium mb-1">Target airfoil: NACA 2412</div>
                  <AirfoilShape coords={targetCoords} height={120} />
                </div>
              )}
              <details className="mt-3">
                <summary className="text-xs text-neutral-500 cursor-pointer">
                  Raw run log (last 25 lines) and manifest
                </summary>
                <p className="mt-2 text-xs text-neutral-600 dark:text-neutral-400">
                  Manifest: <code>{JSON.stringify(data.t7.manifest)}</code>
                </p>
                <div className="mt-1 text-xs font-mono whitespace-pre-wrap text-neutral-600 dark:text-neutral-400 max-h-40 overflow-auto">
                  {data.t7.log_tail}
                </div>
              </details>
            </>
          )}
        </div>
      )}
    </section>
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
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-6">
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 text-sm text-neutral-600 dark:text-neutral-400">
        Runs a self-consistency inverse (recover a NACA airfoil&apos;s own CST coefficients from
        its target Cp, T7-style, forced transition, dossier default config): a falsifiable check
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
      {jobId && (
        <JobStatus
          jobId={jobId}
          job={job}
          targetCoords={targetCoords}
          alphaFree={false}
          targetAirfoilCode={airfoil}
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// raw_target mode: target editor (template-from-airfoil + table edit + CSV
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
  const [templateLoading, setTemplateLoading] = useState(false);
  const [csvUnits, setCsvUnits] = useState<"cp" | "ue">("cp");
  // Tracks which NACA code (if any) the current target curve came from
  // unmodified, so a completed solve can show recovered-vs-target CST
  // coefficients: cleared on upload or manual edit, since the curve no
  // longer has a known parametric target once it diverges from the template.
  const [targetSourceNaca, setTargetSourceNaca] = useState<string | null>(null);

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
    return baselineMode === "naca" ? { naca : baselineNaca }: {};
  }

  async function loadTemplate() {
    setError(null);
    setTemplateLoading(true);
    try {
      const res = await analyze({ naca: templateNaca, alpha: templateAlpha });
      const pts = res.x.map((x, i) => ({ x, cp: res.cp[i] }));
      setPoints(pts);
      setGate(null);
      setTargetSourceNaca(templateNaca);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setTemplateLoading(false);
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
          .map(([x, val]) => ({ x, cp : csvUnits === "cp" ? val : 1 - val * val }));
        if (parsed.length < 5) {
          setError("CSV parsed to fewer than 5 valid (x, value) rows");
          return;
        }
        setPoints(parsed);
        setGate(null);
        setError(null);
        setTargetSourceNaca(null);
      } catch (err) {
        setError(String(err));
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  }

  function updatePoint(i: number, field: "x" | "cp", value: number) {
    setPoints((prev) => prev.map((p, idx) => (idx === i ? { ...p, [field] : value }: p)));
    setTargetSourceNaca(null);
  }

  function buildRawRequest() {
    return {
      baseline: buildBaseline(),
      target: { x: points.map((p) => p.x), cp: points.map((p) => p.cp) },
      constraints: useLeConstraint
        ? [{ type : "le_radius" as const, R_LE : rLe }]
       : [],
      n,
      alpha_deg: alphaDeg,
      alpha_free: alphaFree,
      Re,
    };
  }

  async function checkGate() {
    // Defense in depth only: the button is `disabled` below whenever this
    // would fire, with a tooltip explaining why, so a click should not
    // normally reach here with < 5 points.
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
      setError(describeError(err));
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
      setError(describeError(err));
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
              className={`px-2 py-1 rounded border ${baselineMode === "naca" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900": "border-neutral-300 dark:border-neutral-700"}`}
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
            disabled={templateLoading}
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 py-1.5 text-sm disabled:opacity-50"
          >
            {templateLoading ? "Loading template..." : "Load as target template"}
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
            alpha free (dossier FM-1 absorption DOF: recommended for arbitrary targets)
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
            disabled={gateLoading || points.length < 5}
            title={points.length < 5 ? "Load or upload a target curve first (need >= 5 stations)" : undefined}
            className="flex-1 rounded-md border border-neutral-300 dark:border-neutral-700 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {gateLoading ? "Checking... (up to ~1-2 min)" : "Check realisability"}
          </button>
          <button
            type="button"
            onClick={onRunInverse}
            disabled={submitting || points.length < 5}
            title={points.length < 5 ? "Load or upload a target curve first (need >= 5 stations)" : undefined}
            className="flex-1 rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? "Submitting..." : "Run inverse solve"}
          </button>
        </div>
        {points.length < 5 && (
          <p className="text-xs text-neutral-500">
            {points.length === 0
              ? "Load a target template or upload a CSV above : both buttons need >= 5 target stations."
             : `Only ${points.length} station(s) loaded: need >= 5.`}
          </p>
        )}

        {error && <ErrorBox message={error} />}
      </div>

      <div className="space-y-6">
        {gate && <GateCard gate={gate} />}
        {jobId && (
          <JobStatus jobId={jobId} job={job} alphaFree={alphaFree} targetAirfoilCode={targetSourceNaca} />
        )}
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
        T4 realisability gate : {gate.realisable ? "realisable" : "WARNING : may be outside the CST manifold"}
      </h2>
      <p className="mt-1 text-xs text-neutral-600 dark:text-neutral-400">
        ||M &middot; &Delta;A - (Cp_target - Cp0)|| / ||Cp_target|| = {gate.realisability.toFixed(4)} (threshold{" "}
        {gate.threshold}). {gate.realisable
          ? "The target is within the CST-representable manifold at this baseline : Newton should converge normally."
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
      setError(describeError(err));
      if (timerRef.current) clearInterval(timerRef.current);
    }
  }, POLL_INTERVAL_MS);
}

function JobStatus({
  jobId,
  job,
  targetCoords,
  alphaFree,
  targetAirfoilCode,
}: {
  jobId: string;
  job: InverseJobResponse | null;
  targetCoords?: number[][] | null;
  alphaFree?: boolean;
  /** NACA code the target curve came from unmodified, if known (drives the CST recovered-vs-target readout). */
  targetAirfoilCode?: string | null;
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
      <JobHeartbeat jobId={jobId} job={job} />

      {gate && <GateCard gate={gate} />}

      {stages.length > 0 ? (
        <TheaterStage
          stages={stages}
          targetCoords={targetCoords}
          dof={dof}
          alphaFree={alphaFree}
          narrationExtra={job?.status === "running" ? `phase : ${job.phase}`: undefined}
        />
      ): (
        <div className="text-sm text-neutral-500 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-6 text-center">
          {job?.status === "error"
            ? "Solve failed before the first Newton iteration : see the error below."
           : `${job?.phase ?? "presolving"}... no Newton iteration has landed yet.`}
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
            Verdict : {job.result?.converged ? "converged" : "did not converge"}
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="iterations" value={String(job.result?.iterations ?? ",")} />
            <Stat label="alpha (deg)" value={job.result?.alpha?.toFixed(3) ?? ","} />
            <Stat
              label="convergence order"
              value={job.result?.convergence_order?.toFixed(2) ?? ","}
            />
            <Stat label="realisability" value={job.result?.realisability?.toFixed(4) ?? ","} />
          </div>
          {rv && (
            <div className="mt-3 text-xs text-neutral-600 dark:text-neutral-400">
              <div className="font-medium mb-1">
                release-verify : {rv.ok === undefined ? (rv.converged ? "converged" : "?") : rv.ok ? "PASS" : "FAIL"}
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

      {job?.status === "done" && job.result?.A_upper && job.result?.A_lower && (
        <RecoveredVsTargetCst result={job.result} targetAirfoilCode={targetAirfoilCode} />
      )}
    </div>
  );
}

// Recovered vs target CST coefficients (item 2 of the app rich-features
// brief): once a solve completes, show what the Newton system actually
// recovered next to the target's own CST fit, the same way CstPanel shows
// it everywhere else. The target's coefficients come from the airfoil
// corpus (public/corpus.json) when the target curve is known to have come
// from an unmodified NACA code; otherwise (custom/uploaded targets) only
// the recovered coefficients are shown.
function RecoveredVsTargetCst({
  result,
  targetAirfoilCode,
}: {
  result: InverseResultPayload;
  targetAirfoilCode?: string | null;
}) {
  const [corpus, setCorpus] = useState<CorpusAirfoil[] | null>(null);

  useEffect(() => {
    loadCorpus()
      .then((c) => setCorpus(c.airfoils))
      .catch(() => setCorpus(null));
  }, []);

  if (!result.A_upper || !result.A_lower) return null;

  const targetId = targetAirfoilCode
    ? `naca:${targetAirfoilCode.replace(/^NACA\s*/i, "").trim()}`
    : null;
  const target = targetId ? (corpus?.find((a) => a.id === targetId) ?? null) : null;

  return (
    <CstPanel
      title="CST coefficients: recovered vs target"
      primary={{ label: "recovered", A_upper: result.A_upper, A_lower: result.A_lower }}
      compare={
        target
          ? {
              label: target.name,
              A_upper: target.A_upper,
              A_lower: target.A_lower,
              fitRms: target.fit_rms,
            }
          : null
      }
    />
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

// Defect-fix (job hangs with no visible progress): a ticking elapsed timer
// (client-side, sub-poll-interval smoothness) plus the server's phase text
// and per-phase stage count, so the user always knows the job is alive and
// roughly what it's doing: "Presolving" was previously the ONLY state ever
// shown before the first Newton iteration, indistinguishable from a hang.
function JobHeartbeat({ jobId, job }: { jobId: string; job: InverseJobResponse | null }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  if (!job) {
    return <div className="text-sm text-neutral-600 dark:text-neutral-400">submitting...</div>;
  }
  const elapsed = job.status === "running" || job.status === "queued" ? now - job.created_at : job.elapsed_s;
  const sinceHeartbeat = now - job.updated_at;
  const stages = job.result?.stages ?? [];
  const pctOfTimeout = job.timeout_s > 0 ? Math.min(100, (elapsed / job.timeout_s) * 100) : 0;

  return (
    <div className="text-sm text-neutral-600 dark:text-neutral-400 space-y-1">
      <div>
        job <code className="text-xs">{jobId}</code>: status: <span className="font-mono">{job.status}</span>
        {": "}
        <span className="font-mono">{job.phase}</span>
        {stages.length > 0 && (
          <span className="ml-2 text-neutral-500">({stages.length} Newton iteration(s) so far)</span>
        )}
      </div>
      <div className="flex items-center gap-2 text-xs text-neutral-500">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            job.status === "running" && sinceHeartbeat < 5 ? "bg-emerald-500 animate-pulse" : "bg-neutral-400"
          }`}
          title={`last update ${sinceHeartbeat.toFixed(0)}s ago`}
        />
        <span>elapsed {elapsed.toFixed(0)}s</span>
        {job.status === "running" && (
          <>
            <span>/ timeout {job.timeout_s.toFixed(0)}s</span>
            <div className="h-1.5 w-24 rounded-full bg-neutral-200 dark:bg-neutral-800 overflow-hidden">
              <div className="h-full bg-neutral-500" style={{ width: `${pctOfTimeout}%` }} />
            </div>
          </>
        )}
      </div>
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
