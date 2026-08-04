"use client";

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  pollInverse,
  submitInverse,
  type InverseJobResponse,
} from "@/lib/api";

const POLL_INTERVAL_MS = 1500;

export default function InversePage() {
  const [airfoil, setAirfoil] = useState("2412");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<InverseJobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
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
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = setInterval(async () => {
        try {
          const j = await pollInverse(res.job_id);
          setJob(j);
          if (j.status === "done" || j.status === "error") {
            if (timerRef.current) clearInterval(timerRef.current);
          }
        } catch (err) {
          setError(err instanceof ApiError ? String(err.detail) : String(err));
          if (timerRef.current) clearInterval(timerRef.current);
        }
      }, POLL_INTERVAL_MS);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const history = job?.result?.residual_history ?? [];

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <div className="rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-4 text-sm text-amber-800 dark:text-amber-300">
        <strong>Coming with T8.</strong> Full target-Cp drawing/upload UX ships once T8
        (ablation-cell evidence) closes. This page is already wired end-to-end to the real{" "}
        <code>/api/inverse</code> job API — it runs a self-consistency inverse (recover a NACA
        airfoil&apos;s own CST coefficients from its target Cp, T7-style) so you can watch the
        monolithic Newton solve converge live.
      </div>

      <h1 className="mt-6 text-2xl font-semibold tracking-tight">Inverse</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Submits a monolithic CST-Newton inverse solve as a background job, then polls for status
        and streams the residual history as it arrives.
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex items-end gap-3">
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

      {error && (
        <div className="mt-4 rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {jobId && (
        <div className="mt-6 space-y-4">
          <div className="text-sm text-neutral-600 dark:text-neutral-400">
            job <code>{jobId}</code> — status:{" "}
            <span className="font-mono">{job?.status ?? "queued"}</span>
          </div>

          {history.length > 0 && (
            <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
              <h2 className="text-sm font-medium mb-2">Residual history (‖R‖, log scale)</h2>
              <ResidualChart history={history} />
            </div>
          )}

          {job?.status === "error" && (
            <div className="rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
              {job.error}
            </div>
          )}

          {job?.status === "done" && job.result && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Stat label="converged" value={job.result.converged ? "yes" : "no"} />
              <Stat label="iterations" value={String(job.result.iterations)} />
              <Stat
                label="convergence order"
                value={job.result.convergence_order?.toFixed(2) ?? "—"}
              />
              <Stat
                label="release-verify"
                value={job.result.release_verify?.ok ? "ok" : "check"}
              />
            </div>
          )}
        </div>
      )}
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
