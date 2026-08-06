"use client";

import { useEffect, useRef, useState } from "react";
import AirfoilShape from "@/components/AirfoilShape";
import BLChart from "@/components/BLChart";
import CpChart from "@/components/CpChart";
import CstStudio from "@/components/CstStudio";
import {
  airfoilGeometry,
  analyze,
  describeError,
  fit,
  health,
  listAirfoils,
  uploadAirfoil,
  type AirfoilListItem,
  type AirfoilListResponse,
  type AnalyzeResponse,
  type FitResponse,
} from "@/lib/api";

export default function AnalyzePage() {
  const [naca, setNaca] = useState("2412");
  const [alpha, setAlpha] = useState(2.0);
  const [re, setRe] = useState<number | "">(1.0e6);
  const [ma, setMa] = useState(0.0);
  const [tripEnabled, setTripEnabled] = useState(false);
  const [xtrUpper, setXtrUpper] = useState(0.05);
  const [xtrLower, setXtrLower] = useState(0.05);

  const [loading, setLoading] = useState(false);
  const [elapsedS, setElapsedS] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [fitResult, setFitResult] = useState<FitResponse | null>(null);

  const [catalog, setCatalog] = useState<AirfoilListResponse | null>(null);
  const [catalogFilter, setCatalogFilter] = useState("");
  const [customCoords, setCustomCoords] = useState<number[][] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploadedName, setUploadedName] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  // Free-tier backend wake-up (defect-fix, see lib/api.ts's ANALYZE_TIMEOUT_MS
  // comment): ping /health as soon as the page loads, so a cold Render
  // container starts spinning up before the user has even picked settings,
  // rather than only starting once they click Solve. `waking` flips true
  // only if the ping is still outstanding after 2s (a warm backend answers
  // in well under that), so a warm backend never shows this at all.
  const [waking, setWaking] = useState(false);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listAirfoils()
      .then(setCatalog)
      .catch(() => setCatalog(null));

    let alive = true;
    const showWakingAfter = setTimeout(() => {
      if (alive) setWaking(true);
    }, 2000);
    health()
      .catch(() => {
        // A failed ping isn't fatal here: the actual Solve request is the
        // one that must succeed or report an error; this is only a
        // best-effort warm-up.
      })
      .finally(() => {
        if (alive) {
          clearTimeout(showWakingAfter);
          setWaking(false);
        }
      });
    return () => {
      alive = false;
      clearTimeout(showWakingAfter);
    };
  }, []);

  async function pickAirfoil(item: AirfoilListItem) {
    setSelectedId(item.id);
    setError(null);
    try {
      const geo = await airfoilGeometry(item.id);
      if (item.source === "naca") {
        setNaca(item.name.replace("NACA ", ""));
        setCustomCoords(null);
      } else {
        setCustomCoords(geo.coords);
      }
    } catch (err) {
      setError(describeError(err));
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setElapsedS(0);
    const startedAt = Date.now();
    if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    heartbeatRef.current = setInterval(() => {
      setElapsedS((Date.now() - startedAt) / 1000);
    }, 500);
    try {
      const res = customCoords
        ? await analyze({
            coords: customCoords,
            alpha,
            Re : re === "" ? undefined : re,
            Ma: ma,
            transition: tripEnabled
              ? { mode : "forced", xtr_upper : xtrUpper, xtr_lower : xtrLower }
             : undefined,
          })
       : await analyze({
            naca,
            alpha,
            Re : re === "" ? undefined : re,
            Ma: ma,
            transition: tripEnabled
              ? { mode : "forced", xtr_upper : xtrUpper, xtr_lower : xtrLower }
             : undefined,
          });
      setResult(res);
      try {
        const fitRes = await fit({ coords: res.coords, n: 8 });
        setFitResult(fitRes);
      } catch {
        setFitResult(null);
      }
    } catch (err) {
      setError(describeError(err));
      setResult(null);
      setFitResult(null);
    } finally {
      setLoading(false);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    }
  }

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const res = await uploadAirfoil(file);
      setCustomCoords(res.coords);
      setUploadedName(res.name);
      setSelectedId(null);
    } catch (err) {
      setUploadError(describeError(err));
    } finally {
      setUploading(false);
    }
  }

  const filteredUiuc =
    catalog?.uiuc.filter((a) => a.name.toLowerCase().includes(catalogFilter.toLowerCase())) ?? [];

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Analyze</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Direct mfoil solve on a NACA airfoil (forward analysis): the engine core (
        <code>src/cins/</code>) wrapped by FastAPI, unmodified.
      </p>

      <div className="mt-6 grid gap-8 lg:grid-cols-[280px_1fr]">
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-2">
              Airfoil browser
            </div>
            <input
              className={`${inputCls} mb-2`}
              placeholder="search UIUC sections..."
              value={catalogFilter}
              onChange={(e) => setCatalogFilter(e.target.value)}
            />
            <div className="max-h-40 overflow-auto text-xs space-y-0.5">
              {catalog?.naca.map((a) => (
                <AirfoilRow key={a.id} item={a} selected={selectedId === a.id} onPick={pickAirfoil} />
              ))}
              {filteredUiuc.slice(0, 60).map((a) => (
                <AirfoilRow key={a.id} item={a} selected={selectedId === a.id} onPick={pickAirfoil} />
              ))}
              {!catalog && <div className="text-neutral-400">loading catalog...</div>}
            </div>
            <div className="mt-2 pt-2 border-t border-neutral-200 dark:border-neutral-800">
              <label className="block text-xs text-neutral-500 mb-1">
                Or upload a .dat file (Selig or Lednicer)
              </label>
              <input
                type="file"
                accept=".dat,.txt"
                onChange={onUpload}
                disabled={uploading}
                className="w-full text-xs"
              />
              {uploading && <div className="mt-1 text-xs text-neutral-400">parsing...</div>}
              {uploadedName && !uploading && (
                <div className="mt-1 text-xs text-emerald-600 dark:text-emerald-400">
                  loaded: {uploadedName}
                </div>
              )}
              {uploadError && (
                <div className="mt-1 text-xs text-red-600 dark:text-red-400">{uploadError}</div>
              )}
            </div>
          </div>

          <Field label={customCoords ? "NACA code (unused : custom geometry loaded)" : "NACA code"}>
            <input
              className={inputCls}
              value={naca}
              onChange={(e) => {
                setNaca(e.target.value);
                setCustomCoords(null);
                setSelectedId(null);
              }}
              placeholder="2412"
              maxLength={5}
              disabled={!!customCoords}
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
          <Field label="Mach number (Karman-Tsien, subcritical)">
            <input
              type="number"
              step="0.05"
              min={0}
              max={0.69}
              className={inputCls}
              value={ma}
              onChange={(e) => setMa(Number(e.target.value))}
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

          {waking && !loading && (
            <div className="rounded-md border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-2 text-xs text-amber-800 dark:text-amber-300">
              Waking the backend (free-tier container was asleep)&mdash;this can take up to a
              minute before Solve responds quickly.
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 py-2 text-sm font-medium disabled:opacity-50"
          >
            {loading ? `Solving... (${elapsedS.toFixed(0)}s)` : "Solve"}
          </button>
          {loading && re !== "" && (
            <div className="text-xs text-neutral-500">
              A viscous solve (Reynolds number given) measures ~124s on the free-tier backend
              even when warm, and longer just after a cold start. This will report an error
              below instead of hanging if it does not return within 200s.
            </div>
          )}

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
                <Stat label="cm" value={result.cm.toFixed(4)} />
                <Stat label="alpha" value={`${result.alpha.toFixed(2)}°`} />
                <Stat label="cd (total)" value={result.cd.toFixed(5)} />
                <Stat label="cdf (friction)" value={result.cdf != null ? result.cdf.toFixed(5) : ","} />
                <Stat label="cdp (pressure)" value={result.cdp != null ? result.cdp.toFixed(5) : ","} />
                <Stat label="Re / Ma" value={`${result.Re != null ? result.Re.toExponential(1) : "inviscid"} / ${result.Ma.toFixed(2)}`} />
              </div>
              <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
                <h2 className="text-sm font-medium mb-2">Pressure coefficient</h2>
                <CpChart
                  upper={result.upper}
                  lower={result.lower}
                  upperCpi={result.upper_cpi}
                  lowerCpi={result.lower_cpi}
                  sonicCp={result.sonic_cp}
                />
              </div>
              <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
                <h2 className="text-sm font-medium mb-2">
                  Airfoil shape{result.bl_offset && " with boundary-layer displacement thickness"}
                </h2>
                <AirfoilShape coords={result.coords} blOffset={result.bl_offset} />
              </div>
              {result.bl && (
                <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
                  <h2 className="text-sm font-medium mb-2">Boundary-layer distributions</h2>
                  <BLChart bl={result.bl} />
                </div>
              )}
              {fitResult && (
                <CstStudio key={fitResult.A_upper.join(",") + "|" + fitResult.A_lower.join(",")} fit={fitResult} />
              )}
              {fitResult && (
                <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
                  <h2 className="text-sm font-medium mb-2">
                    CST-derived engineering parameters (order-8 fit)
                  </h2>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <Stat label="LE radius" value={fitResult.derived.le_radius.toFixed(5)} />
                    <Stat
                      label="TE wedge (upper)"
                      value={`${fitResult.derived.te_wedge_upper_deg.toFixed(2)}°`}
                    />
                    <Stat
                      label="TE wedge (lower)"
                      value={`${fitResult.derived.te_wedge_lower_deg.toFixed(2)}°`}
                    />
                    <Stat label="TE gap" value={fitResult.derived.te_gap.toFixed(5)} />
                    <Stat
                      label="max t/c"
                      value={`${(fitResult.derived.max_thickness * 100).toFixed(2)}% @ ${fitResult.derived.max_thickness_x.toFixed(2)}c`}
                    />
                    <Stat
                      label="max camber"
                      value={`${(fitResult.derived.max_camber * 100).toFixed(2)}% @ ${fitResult.derived.max_camber_x.toFixed(2)}c`}
                    />
                    <Stat label="inscribed area" value={fitResult.derived.area.toFixed(4)} />
                  </div>
                </div>
              )}
            </>
          ): (
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

function AirfoilRow({
  item,
  selected,
  onPick,
}: {
  item: AirfoilListItem;
  selected: boolean;
  onPick: (item: AirfoilListItem) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onPick(item)}
      className={`w-full flex justify-between px-2 py-1 rounded text-left ${
        selected
          ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900"
         : "hover:bg-neutral-100 dark:hover:bg-neutral-900"
      }`}
    >
      <span>{item.name}</span>
      {item.thickness != null && (
        <span className="text-neutral-400">{(item.thickness * 100).toFixed(1)}%t</span>
      )}
    </button>
  );
}
