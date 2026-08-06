"use client";

// Minimal reusable XY line plot (same hand-rolled-SVG approach as BLChart /
// CpChart: fixed small multiples, no charting library justified -- see
// CpChart.tsx for the rationale). Extracted from CstPanel.tsx so
// CstBasisFigure.tsx (the gallery's "how a shape is built" panel) can reuse
// the exact same rendering instead of a second hand-rolled copy.

export interface LineSeries {
  x: number[];
  y: number[];
  color: string;
  width?: number;
  opacity?: number;
  dash?: string;
}

export function scaleLinear(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

export default function LinePlot({
  series,
  width = 280,
  height = 150,
  xDomain = [0, 1],
  yDomain,
}: {
  series: LineSeries[];
  width?: number;
  height?: number;
  xDomain?: [number, number];
  yDomain?: [number | undefined, number | undefined];
  xLabel?: string;
  yLabel?: string;
}) {
  const margin = { top: 8, right: 8, bottom: 18, left: 30 };
  const allY = series.flatMap((s) => s.y);
  const yMinData = Math.min(...allY, 0);
  const yMaxData = Math.max(...allY, 0);
  const pad = (yMaxData - yMinData) * 0.1 || 0.01;
  const yMin = yDomain?.[0] ?? yMinData - pad;
  const yMax = yDomain?.[1] ?? yMaxData + pad;

  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const sx = scaleLinear(xDomain, [margin.left, margin.left + innerW]);
  const sy = scaleLinear([yMin, yMax], [margin.top + innerH, margin.top]);

  const zeroY = yMin < 0 && yMax > 0 ? sy(0) : null;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto text-neutral-400 dark:text-neutral-600">
      <line x1={margin.left} x2={width - margin.right} y1={margin.top + innerH} y2={margin.top + innerH} stroke="currentColor" strokeOpacity={0.4} />
      <line x1={margin.left} x2={margin.left} y1={margin.top} y2={margin.top + innerH} stroke="currentColor" strokeOpacity={0.4} />
      {zeroY != null && (
        <line x1={margin.left} x2={width - margin.right} y1={zeroY} y2={zeroY} stroke="currentColor" strokeOpacity={0.2} strokeDasharray="3 3" />
      )}
      {series.map((s, i) => (
        <path
          key={i}
          d={s.x.map((xi, k) => `${k === 0 ? "M" : "L"}${sx(xi).toFixed(2)},${sy(s.y[k]).toFixed(2)}`).join(" ")}
          fill="none"
          stroke={s.color}
          strokeWidth={s.width ?? 1.5}
          strokeOpacity={s.opacity ?? 1}
          strokeDasharray={s.dash}
        />
      ))}
      <text x={sx(0)} y={height - 3} fontSize={9} textAnchor="start" className="fill-neutral-500 dark:fill-neutral-400">
        0
      </text>
      <text x={sx(1)} y={height - 3} fontSize={9} textAnchor="end" className="fill-neutral-500 dark:fill-neutral-400">
        1
      </text>
    </svg>
  );
}
