"use client";

// Makes the CST (Class-Shape Transformation) parameterization visible: the
// coefficients themselves, the class function, the shape function (with its
// Bernstein-term decomposition), and the resulting surface they multiply
// out to. Everything here is computed client-side (src/lib/cst.ts) from
// A_upper/A_lower alone, so this panel works identically wherever a shape is
// in hand: the airfoil corpus (fitted from real coordinates), CST Studio
// (live slider state), and a completed inverse solve (recovered vs target
// coefficients).

import { useMemo } from "react";
import AirfoilShape from "@/components/AirfoilShape";
import LinePlot, { type LineSeries } from "@/components/LinePlot";
import {
  CST_N1_DEFAULT,
  CST_N2_DEFAULT,
  classFunction,
  cstCoords,
  derivedFromCoeffs,
  psiGrid,
  shapeFunction,
} from "@/lib/cst";

export interface CstSeries {
  label: string;
  A_upper: number[];
  A_lower: number[];
  zetaTUpper?: number;
  zetaTLower?: number;
  /** RMS of the least-squares fit to real coordinates, when this series came from one. */
  fitRms?: number | null;
}

interface CstPanelProps {
  primary: CstSeries;
  /** A second series (e.g. an inverse solve's target) overlaid for comparison. */
  compare?: CstSeries | null;
  N1?: number;
  N2?: number;
  title?: string;
}

const UPPER_COLOR = "#3b82f6"; // blue-500
const LOWER_COLOR = "#f97316"; // orange-500
const COMPARE_UPPER_COLOR = "#93c5fd"; // blue-300
const COMPARE_LOWER_COLOR = "#fdba74"; // orange-300

export default function CstPanel({ primary, compare, N1 = CST_N1_DEFAULT, N2 = CST_N2_DEFAULT, title }: CstPanelProps) {
  const psis = useMemo(() => psiGrid(121), []);

  const classSeries = useMemo(() => psis.map((psi) => classFunction(psi, N1, N2)), [psis, N1, N2]);

  const shapeUpper = useMemo(
    () => psis.map((psi) => shapeFunction(psi, primary.A_upper)),
    [psis, primary.A_upper],
  );
  const shapeLower = useMemo(
    () => psis.map((psi) => shapeFunction(psi, primary.A_lower)),
    [psis, primary.A_lower],
  );
  const compareShapeUpper = useMemo(
    () => (compare ? psis.map((psi) => shapeFunction(psi, compare.A_upper)) : null),
    [psis, compare],
  );
  const compareShapeLower = useMemo(
    () => (compare ? psis.map((psi) => shapeFunction(psi, compare.A_lower)) : null),
    [psis, compare],
  );

  const primaryCoords = useMemo(
    () =>
      cstCoords(
        primary.A_upper,
        primary.A_lower,
        primary.zetaTUpper ?? 0,
        primary.zetaTLower ?? 0,
        N1,
        N2,
      ),
    [primary, N1, N2],
  );
  const compareCoords = useMemo(
    () =>
      compare
        ? cstCoords(compare.A_upper, compare.A_lower, compare.zetaTUpper ?? 0, compare.zetaTLower ?? 0, N1, N2)
        : null,
    [compare, N1, N2],
  );

  const primaryDerived = useMemo(
    () =>
      derivedFromCoeffs(
        primary.A_upper,
        primary.A_lower,
        primary.zetaTUpper ?? 0,
        primary.zetaTLower ?? 0,
        N1,
        N2,
      ),
    [primary, N1, N2],
  );
  const compareDerived = useMemo(
    () =>
      compare
        ? derivedFromCoeffs(compare.A_upper, compare.A_lower, compare.zetaTUpper ?? 0, compare.zetaTLower ?? 0, N1, N2)
        : null,
    [compare, N1, N2],
  );

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
      <h2 className="text-sm font-medium">{title ?? "CST parameterization"}</h2>
      <p className="mt-1 text-xs text-neutral-500">
        &zeta;(&psi;) = C(&psi;)&middot;S(&psi;) + &psi;&middot;&zeta;<sub>T</sub>, class function C(&psi;) ={" "}
        &psi;<sup>N1</sup>(1-&psi;)<sup>N2</sup> with N1={N1}, N2={N2}, shape function S(&psi;) = &sum;
        <sub>i</sub> A<sub>i</sub> K<sub>i</sub> &psi;<sup>i</sup>(1-&psi;)<sup>n-i</sup>.
      </p>

      <div className="mt-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
          Coefficients A<sub>upper</sub>, A<sub>lower</sub>
        </div>
        <CoefficientBars
          upper={primary.A_upper}
          lower={primary.A_lower}
          compareUpper={compare?.A_upper}
          compareLower={compare?.A_lower}
        />
        <Legend primary={primary.label} compare={compare?.label} />
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
            Class function C(&psi;)
          </div>
          <LinePlot
            width={280}
            height={150}
            series={[{ x: psis, y: classSeries, color: "#71717a", width: 2 }]}
            yDomain={[0, undefined]}
            xLabel="psi"
            yLabel="C(psi)"
          />
          <p className="mt-1 text-[11px] text-neutral-500">
            Vanishes at &psi;=0 and &psi;=1: the class function alone shapes the round leading edge
            and pinches the trailing edge, before the shape function bends the surface.
          </p>
        </div>

        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
            Resulting surface (class &times; shape)
          </div>
          <AirfoilShape coords={primaryCoords} height={150} margin={10} />
          {compareCoords && (
            <div className="mt-2">
              <AirfoilShape coords={compareCoords} height={150} margin={10} />
            </div>
          )}
          <Legend primary={primary.label} compare={compare?.label} swatch />
        </div>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <ShapeFunctionPlot
          label="Upper surface S(psi)"
          color={UPPER_COLOR}
          compareColor={COMPARE_UPPER_COLOR}
          psis={psis}
          shape={shapeUpper}
          compareShape={compareShapeUpper}
        />
        <ShapeFunctionPlot
          label="Lower surface S(psi)"
          color={LOWER_COLOR}
          compareColor={COMPARE_LOWER_COLOR}
          psis={psis}
          shape={shapeLower}
          compareShape={compareShapeLower}
        />
      </div>

      <div className="mt-5">
        <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
          Derived engineering quantities
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <DerivedStat label="LE radius (A0²/2)" value={primaryDerived.le_radius.toFixed(5)} />
          <DerivedStat
            label="max t/c"
            value={`${(primaryDerived.max_thickness * 100).toFixed(2)}% @ ${primaryDerived.max_thickness_x.toFixed(2)}c`}
          />
          <DerivedStat
            label="max camber"
            value={`${(primaryDerived.max_camber * 100).toFixed(2)}% @ ${primaryDerived.max_camber_x.toFixed(2)}c`}
          />
          <DerivedStat
            label="fit RMS"
            value={primary.fitRms != null ? primary.fitRms.toExponential(2) : "n/a"}
          />
        </div>
        {compare && compareDerived && (
          <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs opacity-70">
            <DerivedStat label={`${compare.label}: LE radius`} value={compareDerived.le_radius.toFixed(5)} />
            <DerivedStat
              label={`${compare.label}: max t/c`}
              value={`${(compareDerived.max_thickness * 100).toFixed(2)}% @ ${compareDerived.max_thickness_x.toFixed(2)}c`}
            />
            <DerivedStat
              label={`${compare.label}: max camber`}
              value={`${(compareDerived.max_camber * 100).toFixed(2)}% @ ${compareDerived.max_camber_x.toFixed(2)}c`}
            />
            <DerivedStat
              label={`${compare.label}: fit RMS`}
              value={compare.fitRms != null ? compare.fitRms.toExponential(2) : "n/a"}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function Legend({ primary, compare, swatch }: { primary: string; compare?: string; swatch?: boolean }) {
  if (!compare) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-neutral-500">
      <span className="inline-flex items-center gap-1">
        {swatch && <span className="inline-block h-2 w-2 rounded-full bg-neutral-700 dark:bg-neutral-300" />}
        {primary} (recovered)
      </span>
      <span className="inline-flex items-center gap-1">
        {swatch && <span className="inline-block h-2 w-2 rounded-full border border-neutral-400" />}
        {compare} (target)
      </span>
    </div>
  );
}

function DerivedStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-neutral-200 dark:border-neutral-800 p-2">
      <div className="text-neutral-500">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

function CoefficientBars({
  upper,
  lower,
  compareUpper,
  compareLower,
}: {
  upper: number[];
  lower: number[];
  compareUpper?: number[];
  compareLower?: number[];
}) {
  const width = 560;
  const height = 160;
  const margin = { top: 8, right: 8, bottom: 20, left: 36 };
  const n = upper.length;
  const hasCompare = !!compareUpper;

  const allVals = [...upper, ...lower, ...(compareUpper ?? []), ...(compareLower ?? [])];
  const vMax = Math.max(...allVals.map(Math.abs), 1e-6) * 1.15;

  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const groupW = innerW / n;
  const zeroY = margin.top + innerH / 2;
  const sy = (v: number) => zeroY - (v / vMax) * (innerH / 2);

  // Each group holds 2 bars (upper, lower) or 4 (+ compare upper, lower),
  // laid out left-to-right with a small gutter, centered in the group.
  const nBars = hasCompare ? 4 : 2;
  const gutter = groupW * 0.12;
  const barW = (groupW - gutter) / nBars;

  const bars: { color: string; value: number }[][] = upper.map((v, i) => {
    const row = [
      { color: UPPER_COLOR, value: v },
      { color: LOWER_COLOR, value: lower[i] },
    ];
    if (hasCompare) {
      row.push({ color: COMPARE_UPPER_COLOR, value: compareUpper![i] });
      row.push({ color: COMPARE_LOWER_COLOR, value: compareLower![i] });
    }
    return row;
  });

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto">
      <line
        x1={margin.left}
        x2={width - margin.right}
        y1={zeroY}
        y2={zeroY}
        stroke="currentColor"
        className="text-neutral-400 dark:text-neutral-600"
        strokeWidth={1}
      />
      {bars.map((row, i) => {
        const gx = margin.left + i * groupW + gutter / 2;
        return (
          <g key={i}>
            {row.map((b, k) => {
              const barY = sy(b.value);
              return (
                <rect
                  key={k}
                  x={gx + k * barW}
                  y={Math.min(barY, zeroY)}
                  width={Math.max(barW - 1, 1)}
                  height={Math.max(Math.abs(barY - zeroY), 0.5)}
                  fill={b.color}
                />
              );
            })}
            <text x={gx + (nBars * barW) / 2} y={height - 6} fontSize={9} textAnchor="middle" className="fill-neutral-500 dark:fill-neutral-400">
              {i}
            </text>
          </g>
        );
      })}
      <text x={4} y={margin.top + 8} fontSize={9} className="fill-neutral-500 dark:fill-neutral-400">
        +{vMax.toFixed(2)}
      </text>
      <text x={4} y={height - margin.bottom} fontSize={9} className="fill-neutral-500 dark:fill-neutral-400">
        -{vMax.toFixed(2)}
      </text>
    </svg>
  );
}

function ShapeFunctionPlot({
  label,
  color,
  compareColor,
  psis,
  shape,
  compareShape,
}: {
  label: string;
  color: string;
  compareColor: string;
  psis: number[];
  shape: { terms: number[]; sum: number }[];
  compareShape?: { terms: number[]; sum: number }[] | null;
}) {
  const n = shape[0]?.terms.length ?? 0;
  const termSeries: LineSeries[] = Array.from({ length: n }, (_, i) => ({
    x: psis,
    y: shape.map((s) => s.terms[i]),
    color,
    width: 1,
    opacity: 0.18,
  }));
  const sumSeries: LineSeries = { x: psis, y: shape.map((s) => s.sum), color, width: 2.5 };
  const series: LineSeries[] = [...termSeries, sumSeries];
  if (compareShape) {
    series.push({ x: psis, y: compareShape.map((s) => s.sum), color: compareColor, width: 2, dash: "4 3" });
  }

  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">{label}</div>
      <LinePlot width={280} height={150} series={series} xLabel="psi" yLabel="S(psi)" />
      <p className="mt-1 text-[11px] text-neutral-500">
        Faint lines: each coefficient&apos;s Bernstein term A<sub>i</sub>K<sub>i</sub>&psi;
        <sup>i</sup>(1-&psi;)<sup>n-i</sup>. Bold: their sum, S(&psi;).
      </p>
    </div>
  );
}

