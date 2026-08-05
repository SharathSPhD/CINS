"use client";

// Plain inline SVG (see CpChart.tsx for the "no charting library" rationale
//: applies identically here: one static closed polyline, no library needed).

import { useMemo } from "react";

interface AirfoilShapeProps {
  /** [x, y] pairs, any chord/units, closed or open loop. */
  coords: number[][];
  /** Displacement-thickness offset curves (mfoil mplot_boundary_layer). */
  blOffset?: { upper: number[][]; lower: number[][] } | null;
  width?: number;
  height?: number;
}

const MARGIN = 20;

export default function AirfoilShape({ coords, blOffset, width = 560, height = 200 }: AirfoilShapeProps) {
  const { path, blUpperPath, blLowerPath, xTicks, sx, sy } = useMemo(() => {
    const allPts = blOffset ? [...coords, ...blOffset.upper, ...blOffset.lower] : coords;
    const xs = allPts.map((p) => p[0]);
    const ys = allPts.map((p) => p[1]);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yAbs = Math.max(...ys.map(Math.abs), 0.05);

    const innerW = width - 2 * MARGIN;
    const innerH = height - 2 * MARGIN;
    const chord = xMax - xMin || 1;
    // Equal x/y scale (true airfoil proportions), sized to fit whichever
    // dimension is tighter.
    const scale = Math.min(innerW / chord, innerH / (2 * yAbs));

    const sxFn = (x: number) => MARGIN + (x - xMin) * scale;
    const syFn = (y: number) => height / 2 - y * scale;

    const toPath = (pts: number[][], close: boolean) =>
      pts.map((p, i) => `${i === 0 ? "M" : "L"}${sxFn(p[0]).toFixed(2)},${syFn(p[1]).toFixed(2)}`).join(" ") +
      (close ? " Z" : "");

    return {
      path: toPath(coords, true),
      blUpperPath : blOffset ? toPath(blOffset.upper, false) : null,
      blLowerPath : blOffset ? toPath(blOffset.lower, false) : null,
      xTicks: [0, 0.25, 0.5, 0.75, 1.0],
      sx: sxFn,
      sy: syFn,
    };
  }, [coords, blOffset, width, height]);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto text-neutral-400 dark:text-neutral-600"
      role="img"
      aria-label={blOffset ? "Airfoil shape with boundary-layer displacement thickness" : "Airfoil shape"}
    >
      <line
        x1={sx(0)}
        x2={sx(1)}
        y1={sy(0)}
        y2={sy(0)}
        stroke="currentColor"
        strokeOpacity={0.3}
        strokeDasharray="4 3"
      />
      <path d={path} fill="#3b82f620" stroke="#111827" className="dark:stroke-neutral-200" strokeWidth={1.5} />
      {blUpperPath && <path d={blUpperPath} fill="none" stroke="#3b82f6" strokeWidth={1.5} />}
      {blLowerPath && <path d={blLowerPath} fill="none" stroke="#f97316" strokeWidth={1.5} />}
      {xTicks.map((t) => (
        <text
          key={t}
          x={sx(t)}
          y={height - 4}
          fontSize={10}
          textAnchor="middle"
          className="fill-neutral-500 dark:fill-neutral-400"
        >
          {t.toFixed(2)}
        </text>
      ))}
      {blOffset && (
        <g transform={`translate(${width - MARGIN - 130}, 8)`}>
          <line x1={0} x2={14} y1={0} y2={0} stroke="#3b82f6" strokeWidth={1.5} />
          <text x={18} y={4} fontSize={10} className="fill-neutral-600 dark:fill-neutral-300">
            {"δ* upper"}
          </text>
          <line x1={0} x2={14} y1={12} y2={12} stroke="#f97316" strokeWidth={1.5} />
          <text x={18} y={16} fontSize={10} className="fill-neutral-600 dark:fill-neutral-300">
            {"δ* lower"}
          </text>
        </g>
      )}
    </svg>
  );
}
