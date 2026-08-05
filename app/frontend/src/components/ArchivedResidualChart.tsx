"use client";

// Shared archived-run residual chart, used by the Inverse page reference
// panel and the Results Gallery so both present the same, fully labelled plot.

// Enriched replay chart (defect-fix: "does not make sense as presented"): // R/T/G drawn as separate labeled series (matching TheaterStage's live
// ConvergencePanel so the archived reference reads as the same kind of plot
// as a live run), explicit log-scale y-axis ticks, an "iteration" x-axis with
// integer ticks, and iteration markers.
export default function ArchivedResidualChart({
  iterations,
}: {
  iterations: { it: number; R_norm: number | null; T_norm: number | null; G_norm: number | null }[];
}) {
  const width = 640;
  const height = 260;
  const margin = { top: 12, right: 12, bottom: 30, left: 48 };
  const floor = 1e-13;
  const series = (key: "R_norm" | "T_norm" | "G_norm") =>
    iterations.map((r) => Math.log10(Math.max(r[key] ?? floor, floor)));
  const rs = series("R_norm");
  const ts = series("T_norm");
  const gs = series("G_norm");
  const all = [...rs, ...ts, ...gs].filter((v) => isFinite(v));
  const yMin = Math.floor(Math.min(...all, -12));
  const yMax = Math.ceil(Math.max(...all, 0));
  const span = yMax - yMin || 1;
  const n = iterations.length;

  const sx = (i: number) =>
    margin.left + (n <= 1 ? 0 : (i / (n - 1)) * (width - margin.left - margin.right));
  const sy = (v: number) => margin.top + (1 - (v - yMin) / span) * (height - margin.top - margin.bottom);
  const toPath = (arr: number[]) =>
    arr.map((v, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(2)},${sy(v).toFixed(2)}`).join(" ");

  const yTicks: number[] = [];
  for (let t = yMax; t >= yMin; t -= 2) yTicks.push(t);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="mt-2 w-full h-auto text-neutral-400 dark:text-neutral-600"
      role="img"
      aria-label="Combined residual norm vs Newton iteration, log scale, R/T/G components"
    >
      {yTicks.map((t) => (
        <g key={t}>
          <line
            x1={margin.left}
            x2={width - margin.right}
            y1={sy(t)}
            y2={sy(t)}
            stroke="currentColor"
            strokeOpacity={0.15}
          />
          <text x={margin.left - 6} y={sy(t) + 3} fontSize={10} textAnchor="end" className="fill-neutral-500 dark:fill-neutral-400">
            {`1e${t}`}
          </text>
        </g>
      ))}
      <line x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} stroke="currentColor" />
      <line x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} stroke="currentColor" />

      <path d={toPath(rs)} fill="none" stroke="#3b82f6" strokeWidth={2} />
      <path d={toPath(ts)} fill="none" stroke="#f97316" strokeWidth={2} />
      <path d={toPath(gs)} fill="none" stroke="#10b981" strokeWidth={2} />
      {iterations.map((r, i) => (
        <g key={r.it}>
          <circle cx={sx(i)} cy={sy(rs[i])} r={3} fill="#3b82f6" />
          <text x={sx(i)} y={height - margin.bottom + 14} fontSize={9} textAnchor="middle" className="fill-neutral-500 dark:fill-neutral-400">
            {r.it}
          </text>
        </g>
      ))}

      <text x={(margin.left + width - margin.right) / 2} y={height - 2} fontSize={11} textAnchor="middle" className="fill-neutral-500 dark:fill-neutral-400">
        Newton iteration
      </text>
      <text x={12} y={margin.top + 8} fontSize={11} className="fill-neutral-500 dark:fill-neutral-400">
        log&#8321;&#8320; residual norm (dimensionless)
      </text>

      <g transform={`translate(${width - margin.right - 150}, ${margin.top + 4})`}>
        <line x1={0} x2={16} y1={0} y2={0} stroke="#3b82f6" strokeWidth={2} />
        <text x={20} y={4} fontSize={11} className="fill-neutral-600 dark:fill-neutral-300">R (flow)</text>
        <line x1={0} x2={16} y1={14} y2={14} stroke="#f97316" strokeWidth={2} />
        <text x={20} y={18} fontSize={11} className="fill-neutral-600 dark:fill-neutral-300">T (target Cp)</text>
        <line x1={0} x2={16} y1={28} y2={28} stroke="#10b981" strokeWidth={2} />
        <text x={20} y={32} fontSize={11} className="fill-neutral-600 dark:fill-neutral-300">G (constraints)</text>
      </g>
    </svg>
  );
}
