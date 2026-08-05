"use client";

// Inverse Design Theater (item 2 of the app rich-features brief): the
// per-iteration ``stages`` array from the backend (app.engine.
// StageCapturingDiagnostics) rendered as an animated staged view — geometry
// panel with target-ghost overlay + LE zoom, Cp panel (current vs target,
// inverted y-axis, stations marked), and a convergence panel (R/T/G, log
// scale) with stage narration + a DOF card. A scrub-bar lets the user replay
// any stage after the run finishes; "live" mode always shows the latest.

import { useMemo, useState } from "react";
import type { DofAccounting, InverseStage } from "@/lib/api";

interface TheaterStageProps {
  stages: InverseStage[];
  targetCoords?: number[][] | null;
  dof?: DofAccounting | null;
  alphaFree?: boolean;
  narrationExtra?: string;
}

function scaleLinear(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

export default function TheaterStage({
  stages,
  targetCoords,
  dof,
  alphaFree,
  narrationExtra,
}: TheaterStageProps) {
  const [scrub, setScrub] = useState<number | null>(null); // null = follow live (latest)
  const idx = scrub ?? stages.length - 1;
  const stage = stages[idx];

  if (!stage) {
    return (
      <div className="text-sm text-neutral-500 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-8 text-center">
        Waiting for the first Newton iteration...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <GeometryPanel coords={stage.coords} target={targetCoords} />
        <CpPanel
          x={stage.cp_stations_x}
          current={stage.cp_current}
          target={stage.cp_target}
        />
      </div>
      <ConvergencePanel stages={stages} idx={idx} dof={dof} alphaFree={alphaFree} extra={narrationExtra} />

      <label className="block">
        <span className="flex justify-between text-xs text-neutral-500 mb-1">
          <span>
            Stage scrub — it={stage.it}
            {scrub === null && stages.length > 0 ? " (live)" : ""}
          </span>
          <button
            type="button"
            className="underline"
            onClick={() => setScrub(null)}
            disabled={scrub === null}
          >
            jump to live
          </button>
        </span>
        <input
          type="range"
          min={0}
          max={Math.max(stages.length - 1, 0)}
          value={idx}
          onChange={(e) => setScrub(Number(e.target.value))}
          className="w-full"
        />
      </label>
    </div>
  );
}

function GeometryPanel({ coords, target }: { coords: number[][]; target?: number[][] | null }) {
  const width = 340, height = 200, margin = 16;
  const { path, targetPath, sx, sy } = useMemo(() => {
    const all = target ? [...coords, ...target] : coords;
    const xs = all.map((p) => p[0]);
    const ys = all.map((p) => p[1]);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yAbs = Math.max(...ys.map(Math.abs), 0.05);
    const innerW = width - 2 * margin, innerH = height - 2 * margin;
    const chord = xMax - xMin || 1;
    const scale = Math.min(innerW / chord, innerH / (2 * yAbs));
    const sxFn = (x: number) => margin + (x - xMin) * scale;
    const syFn = (y: number) => height / 2 - y * scale;
    const toPath = (pts: number[][]) =>
      pts.map((p, i) => `${i === 0 ? "M" : "L"}${sxFn(p[0]).toFixed(2)},${syFn(p[1]).toFixed(2)}`).join(" ") + " Z";
    return {
      path: toPath(coords),
      targetPath: target ? toPath(target) : null,
      sx: sxFn,
      sy: syFn,
    };
  }, [coords, target, width, height, margin]);

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
      <div className="text-xs font-medium mb-1">Geometry (evolving) {target && "— gray = target"}</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto">
        {targetPath && (
          <path d={targetPath} fill="none" stroke="#9ca3af" strokeDasharray="4 3" strokeWidth={1.5} />
        )}
        <path d={path} fill="#3b82f620" stroke="#3b82f6" strokeWidth={2} />
      </svg>
      {/* LE zoom inset */}
      <div className="mt-1 text-[10px] text-neutral-500">LE zoom</div>
      <svg viewBox="0 0 120 80" className="w-32 h-auto border border-neutral-200 dark:border-neutral-800 rounded">
        <g>
          {(() => {
            const leZoomScale = 6;
            const leX = sx(0), leY = sy(0);
            return (
              <>
                {targetPath && (
                  <path
                    d={targetPath}
                    fill="none"
                    stroke="#9ca3af"
                    strokeDasharray="3 2"
                    strokeWidth={1}
                    transform={`translate(${60 - leX * leZoomScale / (width / 60)}, ${40 - leY * leZoomScale / (height / 80)}) scale(${leZoomScale / 3})`}
                  />
                )}
                <path
                  d={path}
                  fill="none"
                  stroke="#3b82f6"
                  strokeWidth={1.2}
                  transform={`translate(${60 - leX * leZoomScale / (width / 60)}, ${40 - leY * leZoomScale / (height / 80)}) scale(${leZoomScale / 3})`}
                />
              </>
            );
          })()}
        </g>
      </svg>
    </div>
  );
}

const CP_MARGIN = { top: 10, right: 10, bottom: 24, left: 36 };
const CONVERGENCE_MARGIN = { top: 10, right: 10, bottom: 24, left: 40 };

function CpPanel({ x, current, target }: { x: number[]; current: number[]; target: number[] }) {
  const width = 340, height = 200;
  const margin = CP_MARGIN;
  // NOTE: stations span BOTH surfaces (QR-pivoted node indices, not split by
  // upper/lower like CpChart.tsx), so a single x-sorted connecting line would
  // zigzag between surfaces at similar x/c — point pairs (current vs target,
  // joined by a thin connector showing the per-station error) read far more
  // clearly than a fake continuous curve here.
  const { pairs } = useMemo(() => {
    const all = [...current, ...target];
    const cpMin = Math.min(...all, -0.2);
    const cpMax = Math.max(...all, 0.2);
    const pad = (cpMax - cpMin) * 0.1 || 0.1;
    const sxFn = scaleLinear([0, 1], [margin.left, width - margin.right]);
    const syFn = scaleLinear([cpMin - pad, cpMax + pad], [height - margin.bottom, margin.top]);
    const syInv = (cp: number) => syFn(cpMax + pad + (cpMin - pad) - cp);
    return {
      pairs: x.map((xi, i) => ({
        sx: sxFn(xi),
        syCur: syInv(current[i]),
        syTgt: syInv(target[i]),
      })),
    };
  }, [x, current, target, width, height, margin]);

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
      <div className="text-xs font-medium mb-1">
        Cp at target stations — current (blue) vs target (gray), connector = error
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto text-neutral-400 dark:text-neutral-600">
        <line x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} stroke="currentColor" />
        <line x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} stroke="currentColor" />
        {pairs.map((p, i) => (
          <line key={`c-${i}`} x1={p.sx} x2={p.sx} y1={p.syCur} y2={p.syTgt} stroke="#9ca3af" strokeWidth={1} strokeOpacity={0.6} />
        ))}
        {pairs.map((p, i) => (
          <circle key={`t-${i}`} cx={p.sx} cy={p.syTgt} r={3} fill="none" stroke="#9ca3af" strokeWidth={1.5} />
        ))}
        {pairs.map((p, i) => (
          <circle key={`c2-${i}`} cx={p.sx} cy={p.syCur} r={2.5} fill="#3b82f6" />
        ))}
        <text x={margin.left} y={height - 4} fontSize={10} className="fill-neutral-500 dark:fill-neutral-400">
          x/c (inverted Cp)
        </text>
      </svg>
    </div>
  );
}

function ConvergencePanel({
  stages,
  idx,
  dof,
  alphaFree,
  extra,
}: {
  stages: InverseStage[];
  idx: number;
  dof?: DofAccounting | null;
  alphaFree?: boolean;
  extra?: string;
}) {
  const width = 700, height = 220;
  const margin = CONVERGENCE_MARGIN;
  const upTo = stages.slice(0, idx + 1);

  const { rPath, tPath, gPath } = useMemo(() => {
    const series = (key: "R_norm" | "T_norm" | "G_norm") =>
      upTo.map((s) => Math.log10(Math.max(s[key] ?? 1e-16, 1e-16)));
    const rs = series("R_norm"), ts = series("T_norm"), gs = series("G_norm");
    const all = [...rs, ...ts, ...gs].filter((v) => isFinite(v));
    const yMin = Math.min(...all, -12);
    const yMax = Math.max(...all, 1);
    const span = yMax - yMin || 1;
    const sxFn = (i: number) =>
      margin.left + (upTo.length <= 1 ? 0 : (i / (upTo.length - 1)) * (width - margin.left - margin.right));
    const syFn = (v: number) => margin.top + (1 - (v - yMin) / span) * (height - margin.top - margin.bottom);
    const toPath = (arr: number[]) => arr.map((v, i) => `${i === 0 ? "M" : "L"}${sxFn(i).toFixed(2)},${syFn(v).toFixed(2)}`).join(" ");
    return { rPath: toPath(rs), tPath: toPath(ts), gPath: toPath(gs) };
  }, [upTo, width, height, margin]);

  const stage = stages[idx];
  const narration = `Newton iteration ${stage.it} — |R|=${(stage.R_norm ?? 0).toExponential(2)}, |T|=${(stage.T_norm ?? 0).toExponential(2)}, |G|=${(stage.G_norm ?? 0).toExponential(2)}, alpha=${stage.alpha.toFixed(3)}°`;

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium">Convergence (log&#8321;&#8320;‖&middot;‖)</h3>
        {dof && (
          <div className="flex gap-3 text-[11px] font-mono text-neutral-500">
            <span>M={dof.M}</span>
            <span>K={dof.K}</span>
            <span>n_free={dof.n_A_free}</span>
            <span>alpha={alphaFree ? "free" : "fixed"}</span>
          </div>
        )}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto text-neutral-400 dark:text-neutral-600">
        <line x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} stroke="currentColor" />
        <line x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} stroke="currentColor" />
        <path d={rPath} fill="none" stroke="#3b82f6" strokeWidth={2} />
        <path d={tPath} fill="none" stroke="#f97316" strokeWidth={2} />
        <path d={gPath} fill="none" stroke="#10b981" strokeWidth={2} />
        <g transform={`translate(${width - margin.right - 150}, ${margin.top + 4})`}>
          <line x1={0} x2={16} y1={0} y2={0} stroke="#3b82f6" strokeWidth={2} />
          <text x={20} y={4} fontSize={11} className="fill-neutral-600 dark:fill-neutral-300">R (flow)</text>
          <line x1={0} x2={16} y1={14} y2={14} stroke="#f97316" strokeWidth={2} />
          <text x={20} y={18} fontSize={11} className="fill-neutral-600 dark:fill-neutral-300">T (target Cp)</text>
          <line x1={0} x2={16} y1={28} y2={28} stroke="#10b981" strokeWidth={2} />
          <text x={20} y={32} fontSize={11} className="fill-neutral-600 dark:fill-neutral-300">G (constraints)</text>
        </g>
      </svg>
      <div className="mt-1 text-xs font-mono text-neutral-600 dark:text-neutral-400">{narration}</div>
      {extra && <div className="mt-0.5 text-xs text-neutral-500">{extra}</div>}
    </div>
  );
}
