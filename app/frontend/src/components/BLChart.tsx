"use client";

// Boundary-layer distribution tabs (item 5 of the app rich-features brief):
// theta / delta* / cf / Hk vs x/c, per surface, with a transition marker.
// Same hand-rolled SVG approach as CpChart.tsx (see its header comment for
// the "no charting library" rationale) — one more fixed XY curve family.

import { useMemo, useState } from "react";
import type { BLDistributions } from "@/lib/api";

interface BLChartProps {
  bl: BLDistributions;
  width?: number;
  height?: number;
}

type Field = "theta" | "delta_star" | "cf" | "Hk";

const FIELD_LABELS: Record<Field, string> = {
  theta: "theta (momentum thickness)",
  delta_star: "delta* (displacement thickness)",
  cf: "cf (skin friction)",
  Hk: "Hk (kinematic shape factor)",
};

const MARGIN = { top: 16, right: 16, bottom: 32, left: 48 };

function scaleLinear(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

function pathFor(x: number[], y: number[], sx: (v: number) => number, sy: (v: number) => number) {
  return x.map((xi, i) => `${i === 0 ? "M" : "L"}${sx(xi).toFixed(2)},${sy(y[i]).toFixed(2)}`).join(" ");
}

export default function BLChart({ bl, width = 560, height = 300 }: BLChartProps) {
  const [field, setField] = useState<Field>("theta");

  const { upperPath, lowerPath, xTicks, yTicks, sx, sy, transitionX } = useMemo(() => {
    const upperY = bl[field].upper;
    const lowerY = bl[field].lower;
    const allY = [...upperY, ...lowerY];
    const yMin = Math.min(...allY, 0);
    const yMax = Math.max(...allY);
    const pad = (yMax - yMin) * 0.08 || 0.001;

    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;
    const sxFn = scaleLinear([0, 1], [MARGIN.left, MARGIN.left + innerW]);
    const syFn = scaleLinear([yMin - pad, yMax + pad], [MARGIN.top + innerH, MARGIN.top]);

    const xt = [0, 0.25, 0.5, 0.75, 1.0];
    const yStep = (yMax - yMin) / 4 || 0.001;
    const yt = Array.from({ length: 5 }, (_, i) => yMin + i * yStep);

    return {
      upperPath: pathFor(bl.x.upper, upperY, sxFn, syFn),
      lowerPath: pathFor(bl.x.lower, lowerY, sxFn, syFn),
      xTicks: xt,
      yTicks: yt,
      sx: sxFn,
      sy: syFn,
      transitionX: bl.transition_x,
    };
  }, [bl, field, width, height]);

  return (
    <div>
      <div className="flex gap-1 mb-2 text-xs">
        {(Object.keys(FIELD_LABELS) as Field[]).map((f) => (
          <button
            key={f}
            onClick={() => setField(f)}
            className={`px-2 py-1 rounded border ${
              field === f
                ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900"
                : "border-neutral-300 dark:border-neutral-700"
            }`}
          >
            {f}
          </button>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-auto text-neutral-400 dark:text-neutral-600"
        role="img"
        aria-label={FIELD_LABELS[field]}
      >
        {xTicks.map((t) => (
          <line
            key={`gx-${t}`}
            x1={sx(t)}
            x2={sx(t)}
            y1={MARGIN.top}
            y2={height - MARGIN.bottom}
            stroke="currentColor"
            strokeOpacity={0.25}
          />
        ))}
        {yTicks.map((t) => (
          <line
            key={`gy-${t}`}
            x1={MARGIN.left}
            x2={width - MARGIN.right}
            y1={sy(t)}
            y2={sy(t)}
            stroke="currentColor"
            strokeOpacity={0.25}
          />
        ))}
        <line
          x1={MARGIN.left}
          x2={width - MARGIN.right}
          y1={height - MARGIN.bottom}
          y2={height - MARGIN.bottom}
          stroke="currentColor"
          strokeWidth={1.5}
        />
        <line
          x1={MARGIN.left}
          x2={MARGIN.left}
          y1={MARGIN.top}
          y2={height - MARGIN.bottom}
          stroke="currentColor"
          strokeWidth={1.5}
        />
        {xTicks.map((t) => (
          <text
            key={`xt-${t}`}
            x={sx(t)}
            y={height - MARGIN.bottom + 16}
            fontSize={11}
            textAnchor="middle"
            className="fill-neutral-500 dark:fill-neutral-400"
          >
            {t.toFixed(2)}
          </text>
        ))}
        {yTicks.map((t) => (
          <text
            key={`yt-${t}`}
            x={MARGIN.left - 8}
            y={sy(t) + 4}
            fontSize={11}
            textAnchor="end"
            className="fill-neutral-500 dark:fill-neutral-400"
          >
            {t.toPrecision(3)}
          </text>
        ))}

        <path d={upperPath} fill="none" stroke="#3b82f6" strokeWidth={2} />
        <path d={lowerPath} fill="none" stroke="#f97316" strokeWidth={2} />

        {transitionX && (
          <>
            <line
              x1={sx(transitionX.upper)}
              x2={sx(transitionX.upper)}
              y1={MARGIN.top}
              y2={height - MARGIN.bottom}
              stroke="#3b82f6"
              strokeDasharray="3 3"
              strokeOpacity={0.7}
            />
            <line
              x1={sx(transitionX.lower)}
              x2={sx(transitionX.lower)}
              y1={MARGIN.top}
              y2={height - MARGIN.bottom}
              stroke="#f97316"
              strokeDasharray="3 3"
              strokeOpacity={0.7}
            />
          </>
        )}

        <g transform={`translate(${width - MARGIN.right - 100}, ${MARGIN.top + 4})`}>
          <line x1={0} x2={16} y1={0} y2={0} stroke="#3b82f6" strokeWidth={2} />
          <text x={20} y={4} fontSize={11} className="fill-neutral-600 dark:fill-neutral-300">
            upper
          </text>
          <line x1={0} x2={16} y1={16} y2={16} stroke="#f97316" strokeWidth={2} />
          <text x={20} y={20} fontSize={11} className="fill-neutral-600 dark:fill-neutral-300">
            lower
          </text>
        </g>
      </svg>
      {transitionX && (
        <div className="text-xs text-neutral-500">
          transition (e^n): upper x/c = {transitionX.upper.toFixed(3)}, lower x/c ={" "}
          {transitionX.lower.toFixed(3)}
        </div>
      )}
    </div>
  );
}
