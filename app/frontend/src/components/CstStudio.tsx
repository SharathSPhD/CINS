"use client";

// CST Studio panel (item 4 of the app rich-features brief): labeled
// coefficient sliders around a fitted CST baseline, driving
// /api/geometry/from-cst live (debounced) for an instant geometry morph +
// derived-params readout. Ties A0 to LE radius and A_n to TE wedge: the
// "linearity story" the dossier's CST parameterization is built on.

import { useEffect, useRef, useState } from "react";
import AirfoilShape from "@/components/AirfoilShape";
import CstPanel from "@/components/CstPanel";
import { ApiError, geometryFromCst, type DerivedGeometry, type FitResponse } from "@/lib/api";

const DEBOUNCE_MS = 150;

interface CstStudioProps {
  fit: FitResponse;
}

// NOTE: this component is deliberately keyed by its fitted coefficients from
// the parent (see AnalyzePage: `<CstStudio key={...} fit={fitResult} />`) so
// that a new fit remounts it: resetting local slider state from props: // instead of syncing props into state via a `useEffect`, which the current
// react-hooks lint rules (set-state-in-effect) flag as an anti-pattern.
export default function CstStudio({ fit }: CstStudioProps) {
  const [aUpper, setAUpper] = useState<number[]>(fit.A_upper);
  const [aLower, setALower] = useState<number[]>(fit.A_lower);
  const [coords, setCoords] = useState<number[][] | null>(null);
  const [derived, setDerived] = useState<DerivedGeometry | null>(fit.derived);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      geometryFromCst({
        A_upper: aUpper,
        A_lower: aLower,
        zeta_T_upper: fit.zeta_T_upper,
        zeta_T_lower: fit.zeta_T_lower,
        N1: fit.N1,
        N2: fit.N2,
      })
        .then((res) => {
          setCoords(res.coords);
          setDerived(res.derived);
          setError(null);
        })
        .catch((err) => setError(err instanceof ApiError ? String(err.detail) : String(err)));
    }, DEBOUNCE_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aUpper, aLower]);

  function resetToFit() {
    setAUpper(fit.A_upper);
    setALower(fit.A_lower);
  }

  function updateCoeff(side: "upper" | "lower", i: number, value: number) {
    if (side === "upper") {
      setAUpper((prev) => prev.map((v, idx) => (idx === i ? value : v)));
    } else {
      setALower((prev) => prev.map((v, idx) => (idx === i ? value : v)));
    }
  }

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-medium">CST Studio: live coefficient morph</h2>
        <button
          type="button"
          onClick={resetToFit}
          className="text-xs rounded border border-neutral-300 dark:border-neutral-700 px-2 py-1"
        >
          Reset to fit
        </button>
      </div>
      <p className="text-xs text-neutral-500 mb-3">
        A_u0/A_l0 set the leading-edge radius (R_LE = A0&sup2;/2); A_un/A_ln set the trailing-edge
        wedge half-angle. Every other coefficient bends the surface in between: the CST basis is
        linear in A, so each slider&apos;s effect on the shape is independent and additive.
      </p>

      <div className="grid gap-6 sm:grid-cols-2">
        <SliderGroup
          label="Upper surface (A_u)"
          values={aUpper}
          fitted={fit.A_upper}
          onChange={(i, v) => updateCoeff("upper", i, v)}
        />
        <SliderGroup
          label="Lower surface (A_l)"
          values={aLower}
          fitted={fit.A_lower}
          onChange={(i, v) => updateCoeff("lower", i, v)}
        />
      </div>

      {error && (
        <div className="mt-3 rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-2 text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {coords && (
        <div className="mt-4">
          <AirfoilShape coords={coords} height={160} />
        </div>
      )}

      {derived && (
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <DerivedStat label="LE radius" value={derived.le_radius.toFixed(5)} />
          <DerivedStat label="TE wedge (u)" value={`${derived.te_wedge_upper_deg.toFixed(2)}°`} />
          <DerivedStat label="TE wedge (l)" value={`${derived.te_wedge_lower_deg.toFixed(2)}°`} />
          <DerivedStat
            label="max t/c"
            value={`${(derived.max_thickness * 100).toFixed(2)}% @ ${derived.max_thickness_x.toFixed(2)}c`}
          />
        </div>
      )}

      <div className="mt-4">
        <CstPanel
          title="CST parameterization (live)"
          primary={{
            label: "current",
            A_upper: aUpper,
            A_lower: aLower,
            zetaTUpper: fit.zeta_T_upper,
            zetaTLower: fit.zeta_T_lower,
            fitRms: fit.rms,
          }}
          N1={fit.N1}
          N2={fit.N2}
        />
      </div>
    </div>
  );
}

function SliderGroup({
  label,
  values,
  fitted,
  onChange,
}: {
  label: string;
  values: number[];
  fitted: number[];
  onChange: (i: number, v: number) => void;
}) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-1">
        {label}
      </div>
      <div className="space-y-2">
        {values.map((v, i) => {
          const base = fitted[i];
          const span = Math.max(Math.abs(base) * 0.3, 0.02);
          return (
            <label key={i} className="block">
              <span className="flex justify-between text-[11px] text-neutral-500 mb-0.5">
                <span>
                  {label.startsWith("Upper") ? "A_u" : "A_l"}
                  {i}
                  {i === 0 ? " (LE)" : i === values.length - 1 ? " (TE)" : ""}
                </span>
                <span className="font-mono">{v.toFixed(4)}</span>
              </span>
              <input
                type="range"
                min={base - span}
                max={base + span}
                step={span / 100}
                value={v}
                onChange={(e) => onChange(i, Number(e.target.value))}
                className="w-full"
              />
            </label>
          );
        })}
      </div>
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
