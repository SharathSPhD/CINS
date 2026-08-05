"use client";

// Results Gallery (item 7 of the app rich-features brief): archived T7
// self-consistency run + T8 NACA panel sweep table + paper figures, all
// read-only over experiments/results/ via GET /api/showcase. Everything here
// is archived evidence, clearly labeled with its manifest (git SHA / date),
// never a live solve.

import { useEffect, useState } from "react";
import { ApiError, showcase, type ShowcaseResponse } from "@/lib/api";

export default function GalleryPage() {
  const [data, setData] = useState<ShowcaseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "converged" | "failed">("all");

  useEffect(() => {
    showcase()
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? String(err.detail) : String(err)));
  }, []);

  if (error) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10">
        <div className="rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 text-sm text-neutral-500">
        Loading archived results...
      </div>
    );
  }

  const rows = data.panel.filter((p) =>
    filter === "all" ? true : filter === "converged" ? p.converged : !p.converged,
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Results Gallery</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        {data.manifest_note}. Everything below is an archived run replayed for reference — not a
        live solve (use Analyze / Inverse / Flow Field for that).
      </p>

      <section className="mt-8">
        <h2 className="text-lg font-medium">T7 self-consistency gate</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          NACA 2412, forced transition — recovers its own CST coefficients from its own target Cp
          in {data.t7.iterations.length} Newton iterations, convergence order{" "}
          {data.t7.convergence_order?.toFixed(3) ?? "—"}.
        </p>
        <div className="mt-3 rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
          <MiniResidualChart history={(data.t7.residual_history.filter((v) => v != null) as number[])} />
          <pre className="mt-3 text-xs font-mono whitespace-pre-wrap text-neutral-600 dark:text-neutral-400 max-h-48 overflow-auto">
            {data.t7.log_tail}
          </pre>
        </div>
      </section>

      <section className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">T8 NACA panel sweep</h2>
          <div className="text-sm text-neutral-600 dark:text-neutral-400">
            {data.panel_n_converged} / {data.panel_n_total} converged
          </div>
        </div>
        <div className="mt-2 flex gap-1 text-xs">
          {(["all", "converged", "failed"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-1 rounded border ${
                filter === f
                  ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900"
                  : "border-neutral-300 dark:border-neutral-700"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="mt-3 max-h-96 overflow-auto rounded-lg border border-neutral-200 dark:border-neutral-800 text-xs">
          <table className="w-full">
            <thead className="sticky top-0 bg-neutral-100 dark:bg-neutral-900">
              <tr>
                <th className="text-left px-3 py-1.5">cell</th>
                <th className="text-left px-3 py-1.5">converged</th>
                <th className="text-left px-3 py-1.5">iterations</th>
                <th className="text-left px-3 py-1.5">err_all_inf</th>
                <th className="text-left px-3 py-1.5">wall time (s)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.cell_name} className="odd:bg-neutral-50 dark:odd:bg-neutral-900/40">
                  <td className="px-3 py-1 font-mono">{p.cell_name}</td>
                  <td className="px-3 py-1">
                    <span className={p.converged ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}>
                      {p.converged ? "yes" : "no"}
                    </span>
                  </td>
                  <td className="px-3 py-1">{p.iterations ?? "—"}</td>
                  <td className="px-3 py-1 font-mono">
                    {p.err_all_inf != null ? p.err_all_inf.toExponential(2) : "—"}
                  </td>
                  <td className="px-3 py-1">{p.wall_time_s?.toFixed(2) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {data.figures.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-medium">Paper figures</h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {data.figures.map((src) => (
              <a key={src} href={src} target="_blank" rel="noreferrer" className="block rounded-lg border border-neutral-200 dark:border-neutral-800 overflow-hidden hover:border-neutral-400 dark:hover:border-neutral-600">
                {/* eslint-disable-next-line @next/next/no-img-element -- static archived PNGs served by the backend, not app-routed assets */}
                <img src={src} alt={src.split("/").pop()} className="w-full h-auto" />
                <div className="px-2 py-1 text-xs text-neutral-500 font-mono truncate">
                  {src.split("/").pop()}
                </div>
              </a>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function MiniResidualChart({ history }: { history: number[] }) {
  if (history.length === 0) return null;
  const width = 560, height = 160;
  const margin = { top: 8, right: 8, bottom: 20, left: 36 };
  const logs = history.map((v) => Math.log10(Math.max(v, 1e-16)));
  const yMin = Math.min(...logs), yMax = Math.max(...logs);
  const span = yMax - yMin || 1;
  const sx = (i: number) =>
    margin.left + (history.length <= 1 ? 0 : (i / (history.length - 1)) * (width - margin.left - margin.right));
  const sy = (v: number) => margin.top + (1 - (v - yMin) / span) * (height - margin.top - margin.bottom);
  const path = logs.map((v, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(2)},${sy(v).toFixed(2)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto text-neutral-400 dark:text-neutral-600">
      <line x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} stroke="currentColor" />
      <line x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} stroke="currentColor" />
      <path d={path} fill="none" stroke="#3b82f6" strokeWidth={2} />
      {logs.map((v, i) => (
        <circle key={i} cx={sx(i)} cy={sy(v)} r={3} fill="#3b82f6" />
      ))}
      <text x={margin.left} y={height - 4} fontSize={10} className="fill-neutral-500 dark:fill-neutral-400">
        iteration
      </text>
      <text x={2} y={margin.top + 8} fontSize={10} className="fill-neutral-500 dark:fill-neutral-400">
        log10‖R‖
      </text>
    </svg>
  );
}
