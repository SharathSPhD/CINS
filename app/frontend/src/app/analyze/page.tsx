"use client";

import { useState } from "react";
import AirfoilShape from "@/components/AirfoilShape";
import CpChart from "@/components/CpChart";
import { analyze, ApiError, type AnalyzeResponse } from "@/lib/api";

export default function AnalyzePage() {
  const [naca, setNaca] = useState("2412");
  const [alpha, setAlpha] = useState(2.0);
  const [re, setRe] = useState<number | "">(1.0e6);
  const [tripEnabled, setTripEnabled] = useState(false);
  const [xtrUpper, setXtrUpper] = useState(0.05);
  const [xtrLower, setXtrLower] = useState(0.05);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await analyze({
        naca,
        alpha,
        Re: re === "" ? undefined : re,
        transition: tripEnabled
          ? { mode: "forced", xtr_upper: xtrUpper, xtr_lower: xtrLower }
          : undefined,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : String(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Analyze</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Direct mfoil solve on a NACA airfoil (forward analysis) — the engine core (
        <code>src/cins/</code>) wrapped by FastAPI, unmodified.
      </p>

      <div className="mt-6 grid gap-8 lg:grid-cols-[280px_1fr]">
        <form onSubmit={onSubmit} className="space-y-4">
          <Field label="NACA code">
            <input
              className={inputCls}
              value={naca}
              onChange={(e) => setNaca(e.target.value)}
              placeholder="2412"
              maxLength={5}
            />
          </Field>
          <Field label="Angle of attack (deg)">
            <input
              type="number"
              step="0.1"
              className={inputCls}
              value={alpha}
              onChange={(e) => setAlpha(Number(e.target.value))}
            />
          </Field>
          <Field label="Reynolds number (blank = inviscid)">
            <input
              type="number"
              step="1000"
              className={inputCls}
              value={re}
              onChange={(e) => setRe(e.target.value === "" ? "" : Number(e.target.value))}
              placeholder="1000000"
            />
          </Field>

          <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3 space-y-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={tripEnabled}
                onChange={(e) => setTripEnabled(e.target.checked)}
                disabled={re === ""}
              />
              Forced transition (trip)
            </label>
            {tripEnabled && (
              <>
                <Field label="Trip x/c, upper">
                  <input
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    className={inputCls}
                    value={xtrUpper}
                    onChange={(e) => setXtrUpper(Number(e.target.value))}
                  />
                </Field>
                <Field label="Trip x/c, lower">
                  <input
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    className={inputCls}
                    value={xtrLower}
                    onChange={(e) => setXtrLower(Number(e.target.value))}
                  />
                </Field>
              </>
            )}
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 py-2 text-sm font-medium disabled:opacity-50"
          >
            {loading ? "Solving..." : "Solve"}
          </button>

          {error && (
            <div className="rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}
        </form>

        <div className="space-y-6">
          {result ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Stat label="converged" value={result.converged ? "yes" : "no"} />
                <Stat label="cl" value={result.cl.toFixed(4)} />
                <Stat label="cd" value={result.cd.toFixed(5)} />
                <Stat label="cm" value={result.cm.toFixed(4)} />
              </div>
              <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
                <h2 className="text-sm font-medium mb-2">Pressure coefficient</h2>
                <CpChart upper={result.upper} lower={result.lower} />
              </div>
              <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
                <h2 className="text-sm font-medium mb-2">Airfoil shape</h2>
                <AirfoilShape coords={result.coords} />
              </div>
            </>
          ) : (
            <div className="text-sm text-neutral-500 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-8 text-center">
              Run a solve to see Cp and coefficients.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-neutral-600 dark:text-neutral-400 mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-lg font-mono">{value}</div>
    </div>
  );
}
