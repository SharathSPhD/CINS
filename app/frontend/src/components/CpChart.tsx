"use client";

// Plain inline SVG, no charting library.
//
// Justification (phase-1 scope, PRD FR-8/FR-9): the app needs exactly two
// plots (a Cp-vs-x/c curve and an airfoil outline), both static per solve —
// no brushing, zooming, or animated transitions. Recharts/visx pull in a
// dependency tree (d3 scale/shape modules, React context providers) sized
// for many-series interactive dashboards; for two fixed XY curves, hand-built
// SVG with a handful of scale helpers is fewer lines than the *types* for a
// chart-library config, has zero bundle cost, and gives full control over
// the aero-convention inverted y-axis without fighting a library's default
// axis orientation. If phase 2 adds interactive target-Cp drawing/brushing,
// that's the point to reconsider visx (lower-level, composable, matches
// this same "own the SVG" style).

import { useMemo } from "react";
import type { SurfaceCp } from "@/lib/api";

interface CpChartProps {
  upper: SurfaceCp;
  lower: SurfaceCp;
  width?: number;
  height?: number;
}

const MARGIN = { top: 16, right: 16, bottom: 32, left: 44 };

function scaleLinear(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

function pathFor(x: number[], y: number[], sx: (v: number) => number, sy: (v: number) => number) {
  return x.map((xi, i) => `${i === 0 ? "M" : "L"}${sx(xi).toFixed(2)},${sy(y[i]).toFixed(2)}`).join(" ");
}

export default function CpChart({ upper, lower, width = 560, height = 360 }: CpChartProps) {
  const { upperPath, lowerPath, xTicks, yTicks, sx, sy } = useMemo(() => {
    const allCp = [...upper.cp, ...lower.cp];
    const cpMin = Math.min(...allCp, -0.2);
    const cpMax = Math.max(...allCp, 0.2);
    const pad = (cpMax - cpMin) * 0.08 || 0.1;

    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;

    const sxFn = scaleLinear([0, 1], [MARGIN.left, MARGIN.left + innerW]);
    // Cp axis inverted: aero convention plots -Cp (suction) upward.
    const syFn = scaleLinear([cpMin - pad, cpMax + pad], [MARGIN.top, MARGIN.top + innerH]);
    const syInv = (cp: number) => syFn(cpMax + pad + (cpMin - pad) - cp);

    const xt = [0, 0.25, 0.5, 0.75, 1.0];
    const cpStep = (cpMax - cpMin) / 4 || 0.1;
    const yt = Array.from({ length: 5 }, (_, i) => cpMin + i * cpStep);

    return {
      upperPath: pathFor(upper.x, upper.cp, sxFn, syInv),
      lowerPath: pathFor(lower.x, lower.cp, sxFn, syInv),
      xTicks: xt,
      yTicks: yt,
      sx: sxFn,
      sy: syInv,
    };
  }, [upper, lower, width, height]);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto text-neutral-400 dark:text-neutral-600"
      role="img"
      aria-label="Pressure coefficient distribution, upper and lower surfaces"
    >
      {/* gridlines */}
      {xTicks.map((t) => (
        <line
          key={`gx-${t}`}
          x1={sx(t)}
          x2={sx(t)}
          y1={MARGIN.top}
          y2={height - MARGIN.bottom}
          stroke="currentColor"
          strokeOpacity={0.25}
          strokeWidth={1}
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
          strokeWidth={1}
        />
      ))}

      {/* axes */}
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
          {t.toFixed(2)}
        </text>
      ))}

      <text
        x={(MARGIN.left + width - MARGIN.right) / 2}
        y={height - 4}
        fontSize={12}
        textAnchor="middle"
        className="fill-neutral-500 dark:fill-neutral-400"
      >
        x / c
      </text>
      <text
        x={14}
        y={(MARGIN.top + height - MARGIN.bottom) / 2}
        fontSize={12}
        textAnchor="middle"
        transform={`rotate(-90, 14, ${(MARGIN.top + height - MARGIN.bottom) / 2})`}
        className="fill-neutral-500 dark:fill-neutral-400"
      >
        Cp (inverted)
      </text>

      {/* curves */}
      <path d={upperPath} fill="none" stroke="#3b82f6" strokeWidth={2} />
      <path d={lowerPath} fill="none" stroke="#f97316" strokeWidth={2} />

      {/* legend */}
      <g transform={`translate(${width - MARGIN.right - 96}, ${MARGIN.top + 4})`}>
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
  );
}
