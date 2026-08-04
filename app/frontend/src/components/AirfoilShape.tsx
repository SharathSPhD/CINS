"use client";

// Plain inline SVG (see CpChart.tsx for the "no charting library" rationale
// — applies identically here: one static closed polyline, no library needed).

import { useMemo } from "react";

interface AirfoilShapeProps {
  /** [x, y] pairs, any chord/units, closed or open loop. */
  coords: number[][];
  width?: number;
  height?: number;
}

const MARGIN = 20;

export default function AirfoilShape({ coords, width = 560, height = 200 }: AirfoilShapeProps) {
  const { path, xTicks, sx, sy } = useMemo(() => {
    const xs = coords.map((p) => p[0]);
    const ys = coords.map((p) => p[1]);
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

    const d =
      coords
        .map((p, i) => `${i === 0 ? "M" : "L"}${sxFn(p[0]).toFixed(2)},${syFn(p[1]).toFixed(2)}`)
        .join(" ") + " Z";

    return { path: d, xTicks: [0, 0.25, 0.5, 0.75, 1.0], sx: sxFn, sy: syFn };
  }, [coords, width, height]);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto text-neutral-400 dark:text-neutral-600"
      role="img"
      aria-label="Airfoil shape"
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
      <path d={path} fill="#3b82f620" stroke="#3b82f6" strokeWidth={2} />
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
    </svg>
  );
}
