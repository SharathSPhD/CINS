"use client";

// "How a shape is built from its CST components" -- the client-side mirror
// of src/cins/benchmarks/paper_figures_theory.py::fig_cst_basis, reproduced
// with the same four-panel decomposition (class function -> Bernstein shape
// functions -> A-weighted terms -> reconstructed surface) using the same
// math (app/frontend/src/lib/cst.ts, kept independent of the backend so this
// never waits on a solve) against real per-section data already in hand
// (public/corpus.json's A_upper/A_lower CST fit).
//
// The point this figure makes (verbatim from the paper function's own
// docstring, restated for a web reader below): only the class-function panel
// is nonlinear in anything. The class function is fixed geometry -- it does
// not depend on the coefficients A at all. The shape functions are fixed
// polynomials. The surface is just their A-weighted sum. That linearity is
// why appending CST coefficients to the Newton system keeps the geometric
// Jacobian block constant.

import { useMemo } from "react";
import LinePlot, { type LineSeries } from "@/components/LinePlot";
import {
  CST_N1_DEFAULT,
  CST_N2_DEFAULT,
  bernsteinBasis,
  classFunction,
  classShapeWeightedTerms,
  cstCoords,
  psiGrid,
} from "@/lib/cst";

const C_BLUE = "#0072B2";
const C_GRAY = "#666666";
const C_VERMILLION = "#D55E00";

interface CstBasisFigureProps {
  name: string;
  A_upper: number[];
  A_lower: number[];
  zetaTUpper?: number;
  zetaTLower?: number;
  N1?: number;
  N2?: number;
  /** The real digitized outline this A_upper/A_lower was fitted to, for panel (d). */
  sourceCoords?: number[][] | null;
  fitRms?: number | null;
}

export default function CstBasisFigure({
  name,
  A_upper,
  A_lower,
  zetaTUpper = 0,
  zetaTLower = 0,
  N1 = CST_N1_DEFAULT,
  N2 = CST_N2_DEFAULT,
  sourceCoords,
  fitRms,
}: CstBasisFigureProps) {
  const psis = useMemo(() => psiGrid(161), []);
  const n = A_upper.length - 1;

  // (a) Class function: the default round-nose/sharp-TE shape used
  // everywhere else in this app, alongside two named alternatives, to show
  // that C(psi) is a choice of N1/N2 fixed BEFORE any coefficient is fit --
  // it carries no information about this particular airfoil.
  const classSeries: LineSeries[] = useMemo(
    () => [
      { x: psis, y: psis.map((p) => classFunction(p, 1.0, 1.0)), color: C_GRAY, width: 1.5, dash: "2 3", opacity: 0.8 },
      { x: psis, y: psis.map((p) => classFunction(p, 0.5, 0.5)), color: C_GRAY, width: 1.5, dash: "6 3", opacity: 0.8 },
      { x: psis, y: psis.map((p) => classFunction(p, N1, N2)), color: C_BLUE, width: 2.5 },
    ],
    [psis, N1, N2],
  );

  // (b) The Bernstein basis itself, unweighted by any A_i: fixed polynomials
  // that do not change no matter which airfoil is selected.
  const basisSeries: LineSeries[] = useMemo(() => {
    const perPsi = psis.map((p) => bernsteinBasis(p, n));
    return Array.from({ length: n + 1 }, (_, i) => ({
      x: psis,
      y: perPsi.map((row) => row[i]),
      color: C_BLUE,
      width: 1.4,
      opacity: 0.75,
    }));
  }, [psis, n]);

  // (c) The A-weighted, class-multiplied terms and their sum: the only panel
  // where this airfoil's own coefficients appear, and they appear linearly.
  const weighted = useMemo(() => psis.map((p) => classShapeWeightedTerms(p, A_upper, N1, N2)), [psis, A_upper, N1, N2]);
  const weightedSeries: LineSeries[] = useMemo(() => {
    const termSeries: LineSeries[] = Array.from({ length: n + 1 }, (_, i) => ({
      x: psis,
      y: weighted.map((w) => w.terms[i]),
      color: C_VERMILLION,
      width: 1.2,
      opacity: 0.3,
    }));
    return [...termSeries, { x: psis, y: weighted.map((w) => w.sum), color: "#111827", width: 2.5 }];
  }, [psis, weighted, n]);

  // (d) The reconstructed surface: upper + lower CST curves against the real
  // digitized outline this fit came from (when supplied).
  const reconstructed = useMemo(
    () => cstCoords(A_upper, A_lower, zetaTUpper, zetaTLower, N1, N2, 121),
    [A_upper, A_lower, zetaTUpper, zetaTLower, N1, N2],
  );

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
      <h3 className="text-sm font-medium">How {name}&apos;s shape is built from its CST components</h3>
      <p className="mt-1 text-xs text-neutral-500">
        &zeta;(&psi;) = C(&psi;)&middot;S(&psi;) + &psi;&middot;&zeta;<sub>T</sub>, order n={n}. Only
        panel (a) depends on a choice fixed in advance (N1, N2); only panel (c) depends on this
        airfoil&apos;s own coefficients, A<sub>0</sub>&hellip;A<sub>{n}</sub>, and it depends on
        them linearly&mdash;each faint curve is one coefficient&apos;s fixed basis function scaled
        by A<sub>i</sub>, and the bold curve is their sum.
      </p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
            (a) Class function C(&psi;) = &psi;<sup>N1</sup>(1-&psi;)<sup>N2</sup>
          </div>
          <LinePlot width={280} height={150} series={classSeries} yDomain={[0, undefined]} />
          <p className="mt-1 text-[11px] text-neutral-500">
            Bold: N1={N1}, N2={N2} (round nose, sharp-ish trailing edge&mdash;used everywhere in
            this app). Dashed: N1=N2=1 (wedge) and N1=N2=0.5 (ellipse), shown for contrast. Fixed
            geometry, independent of A.
          </p>
        </div>

        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
            (b) Bernstein shape functions S<sub>i</sub>(&psi;), n={n}
          </div>
          <LinePlot width={280} height={150} series={basisSeries} />
          <p className="mt-1 text-[11px] text-neutral-500">
            S<sub>i</sub> = K<sub>i</sub>&psi;<sup>i</sup>(1-&psi;)<sup>n-i</sup>, K<sub>i</sub> the
            binomial coefficient. {n + 1} fixed polynomials, unweighted&mdash;the same for every
            airfoil at this order.
          </p>
        </div>

        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
            (c) Weighted terms A<sub>i</sub>&middot;C(&psi;)&middot;S<sub>i</sub>(&psi;) and their sum
          </div>
          <LinePlot width={280} height={150} series={weightedSeries} />
          <p className="mt-1 text-[11px] text-neutral-500">
            Faint: each upper-surface coefficient&apos;s contribution. Bold: C(&psi;)S(&psi;), their
            sum&mdash;this airfoil&apos;s upper-surface shape (before the &psi;&middot;&zeta;
            <sub>T</sub> trailing-edge offset).
          </p>
        </div>

        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
            (d) The surface the coefficients describe
          </div>
          <ReconstructionOverlay reconstructed={reconstructed} source={sourceCoords ?? null} />
          <p className="mt-1 text-[11px] text-neutral-500">
            {sourceCoords ? (
              <>
                Gray: the digitized section. Vermillion: the order-{n} CST reconstruction from
                A<sub>upper</sub>, A<sub>lower</sub> above
                {fitRms != null ? ` (fit RMS ${fitRms.toExponential(2)} c)` : ""}.
              </>
            ) : (
              <>The order-{n} CST reconstruction from A<sub>upper</sub>, A<sub>lower</sub> above.</>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

// Two-series airfoil overlay (source outline vs CST reconstruction) on a
// shared equal-aspect scale: AirfoilShape (components/AirfoilShape.tsx) only
// draws one polygon (plus an optional BL-offset pair), so this is a small
// dedicated overlay in the same hand-rolled-SVG style (see CpChart.tsx for
// why: two fixed static curves, no charting library justified).
function ReconstructionOverlay({
  reconstructed,
  source,
  width = 280,
  height = 150,
  margin = 14,
}: {
  reconstructed: number[][];
  source: number[][] | null;
  width?: number;
  height?: number;
  margin?: number;
}) {
  const { reconPath, sourcePath } = useMemo(() => {
    const allPts = source ? [...reconstructed, ...source] : reconstructed;
    const xs = allPts.map((p) => p[0]);
    const ys = allPts.map((p) => p[1]);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yAbs = Math.max(...ys.map(Math.abs), 0.03);

    const innerW = width - 2 * margin;
    const innerH = height - 2 * margin;
    const chord = xMax - xMin || 1;
    const scale = Math.min(innerW / chord, innerH / (2 * yAbs));

    const sx = (x: number) => margin + (x - xMin) * scale;
    const sy = (y: number) => height / 2 - y * scale;
    const toPath = (pts: number[][]) =>
      pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p[0]).toFixed(2)},${sy(p[1]).toFixed(2)}`).join(" ") + " Z";

    return {
      reconPath: toPath(reconstructed),
      sourcePath: source ? toPath(source) : null,
    };
  }, [reconstructed, source, width, height, margin]);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto" role="img" aria-label="CST reconstruction vs source outline">
      {sourcePath && <path d={sourcePath} fill="none" stroke={C_GRAY} strokeWidth={3} strokeOpacity={0.5} />}
      <path d={reconPath} fill="none" stroke={C_VERMILLION} strokeWidth={1.6} />
    </svg>
  );
}
