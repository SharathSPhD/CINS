"use client";

import { useEffect, useRef, useState } from "react";
import AirfoilShape from "@/components/AirfoilShape";
import BLChart from "@/components/BLChart";
import FlowFieldCanvas from "@/components/FlowFieldCanvas";
import {
  airfoilGeometry,
  analyze,
  describeError,
  flowFieldViaJob,
  listAirfoils,
  type AirfoilListItem,
  type AirfoilListResponse,
  type AnalyzeResponse,
  type FlowFieldResponse,
} from "@/lib/api";

const DEBOUNCE_MS = 350;

export default function FlowFieldPage() {
  const [naca, setNaca] = useState("2412");
  const [customCoords, setCustomCoords] = useState<number[][] | null>(null);
  const [alpha, setAlpha] = useState(4.0);
  const [re, setRe] = useState<number | "">("");
  const [colorBy, setColorBy] = useState<"speed" | "cp">("speed");
  const [showStreamlines, setShowStreamlines] = useState(true);

  const [catalog, setCatalog] = useState<AirfoilListResponse | null>(null);
  const [catalogFilter, setCatalogFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [field, setField] = useState<FlowFieldResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [elapsedS, setElapsedS] = useState(0);
  // The field runs about a minute and a half on the free-tier container,
  // so the wait needs to show what it is doing.
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Viscous half of the same coupled solve, via the existing /api/analyze
  // endpoint: mfoil couples the inviscid field and the boundary layer
  // through the displacement thickness, and that coupling is why mfoil was
  // chosen (see CLAUDE.md). The color field above stays inviscid (a
  // separate change adds the viscous source term to the field itself); this
  // panel is what /api/analyze already returns for the same airfoil/alpha,
  // so the page stops presenting itself as inviscid-only without claiming
  // the field is something it is not yet.
  const [blResult, setBlResult] = useState<AnalyzeResponse | null>(null);
  const [blLoading, setBlLoading] = useState(false);
  const [blError, setBlError] = useState<string | null>(null);

  useEffect(() => {
    listAirfoils()
      .then(setCatalog)
      .catch(() => setCatalog(null));
    return () => {
      setPhase(null);
    if (heartbeatRef.current) clearInterval(heartbeatRef.current);
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

  async function runSolve() {
    // Defect-fix: a stale, slower-to-resolve request (e.g. from a debounced
    // slider drag) landing AFTER a newer one previously overwrote `field`
    // with a wrong/older result silently: track which request is current
    // and drop any response that isn't it anymore.
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    setElapsedS(0);
    const startedAt = Date.now();
    if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    heartbeatRef.current = setInterval(() => {
      setElapsedS((Date.now() - startedAt) / 1000);
    }, 500);

    const baseReq = customCoords ? { coords: customCoords, alpha } : { naca, alpha };

    const fieldPromise = flowFieldViaJob(baseReq, setPhase)
      .then((res) => {
        if (requestId !== requestIdRef.current) return;
        setField(res);
      })
      .catch((err) => {
        if (requestId !== requestIdRef.current) return;
        setError(describeError(err));
      });

    // Viscous boundary-layer distributions for the SAME airfoil/alpha, via
    // the coupled mfoil solve: only fired when a Reynolds number is given
    // (blank stays inviscid, matching the field above).
    let blPromise: Promise<void> = Promise.resolve();
    if (re !== "") {
      setBlLoading(true);
      setBlError(null);
      blPromise = analyze({ ...baseReq, Re: re })
        .then((res) => {
          if (requestId !== requestIdRef.current) return;
          setBlResult(res);
        })
        .catch((err) => {
          if (requestId !== requestIdRef.current) return;
          setBlResult(null);
          setBlError(describeError(err));
        })
        .finally(() => {
          if (requestId === requestIdRef.current) setBlLoading(false);
        });
    } else {
      setBlResult(null);
      setBlError(null);
      setBlLoading(false);
    }

    await Promise.allSettled([fieldPromise, blPromise]);
    if (requestId === requestIdRef.current) {
      setLoading(false);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    }
  }

  function onAlphaChange(v: number) {
    setAlpha(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSolve();
    }, DEBOUNCE_MS);
  }

  const filteredUiuc =
    catalog?.uiuc.filter((a) => a.name.toLowerCase().includes(catalogFilter.toLowerCase())) ?? [];

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Flow Field</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        mfoil is a coupled viscous-inviscid solver, and that coupling is why it was chosen for
        this project. The colour field below is the <strong>inviscid</strong> part (vendor{" "}
        <code>inviscid_velocity</code>), rendered as a |V| or Cp heatmap with client-side RK2
        streamline tracing, for any NACA code or UIUC section.
      </p>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Give a Reynolds number below and this page also runs the same solve with the boundary
        layer on (the existing <code>/api/analyze</code> endpoint) and shows its{" "}
        <strong>viscous</strong> half alongside the field: momentum/displacement thickness growing
        along the chord, with the transition location marked. Displacement thickness{" "}
        <code>delta*</code> is what couples the two halves of the solve. The colour field itself
        stays inviscid for now: adding the viscous source contribution to the field is a separate
        change.
      </p>

      <div className="mt-6 grid gap-8 lg:grid-cols-[280px_1fr]">
        <div className="space-y-4">
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
          </div>

          <label className="block">
            <span className="block text-xs font-medium text-neutral-600 dark:text-neutral-400 mb-1">
              {customCoords ? "NACA code (unused : custom geometry loaded)" : "NACA code"}
            </span>
            <input
              className={inputCls}
              value={naca}
              onChange={(e) => {
                setNaca(e.target.value);
                setCustomCoords(null);
                setSelectedId(null);
              }}
              maxLength={5}
              disabled={!!customCoords}
            />
          </label>

          <label className="block">
            <span className="flex justify-between text-xs font-medium text-neutral-600 dark:text-neutral-400 mb-1">
              <span>Angle of attack</span>
              <span className="font-mono">{alpha.toFixed(1)}&deg;</span>
            </span>
            <input
              type="range"
              min={-15}
              max={15}
              step={0.5}
              value={alpha}
              onChange={(e) => onAlphaChange(Number(e.target.value))}
              className="w-full"
            />
          </label>

          <label className="block">
            <span className="block text-xs font-medium text-neutral-600 dark:text-neutral-400 mb-1">
              Reynolds number (blank = inviscid boundary layer, no BL panels)
            </span>
            <input
              type="number"
              step="1000"
              className={inputCls}
              value={re}
              onChange={(e) => setRe(e.target.value === "" ? "" : Number(e.target.value))}
              placeholder="1000000"
            />
          </label>

          <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3 space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Display
            </div>
            <div className="flex gap-2 text-xs">
              <button
                className={`flex-1 px-2 py-1 rounded border ${colorBy === "speed" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900": "border-neutral-300 dark:border-neutral-700"}`}
                onClick={() => setColorBy("speed")}
              >
                |V| magnitude
              </button>
              <button
                className={`flex-1 px-2 py-1 rounded border ${colorBy === "cp" ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900": "border-neutral-300 dark:border-neutral-700"}`}
                onClick={() => setColorBy("cp")}
              >
                Cp contour
              </button>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={showStreamlines}
                onChange={(e) => setShowStreamlines(e.target.checked)}
              />
              Streamlines
            </label>
          </div>

          <button
            type="button"
            onClick={runSolve}
            disabled={loading}
            className="w-full rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 py-2 text-sm font-medium disabled:opacity-50"
          >
            {loading
              ? `${phase ? phase[0].toUpperCase() + phase.slice(1) : "Solving"}... (${elapsedS.toFixed(0)}s)`
              : "Solve"}
          </button>
          {loading && elapsedS > 5 && (
            <div className="text-xs text-neutral-500">
              The inviscid field is normally well under a second once the backend is warm; a
              longer wait usually means a free-tier backend is cold-starting (this will show an
              error below instead of hanging if it does not come back within 90s).
              {re !== "" && (
                <>
                  {" "}
                  The viscous boundary-layer panel below (Reynolds number given) is slower&mdash;
                  measured 124-192s on the free-tier backend even when warm&mdash;and has its own
                  240s budget.
                </>
              )}
            </div>
          )}

          {error && <ErrorBox message={error} />}
        </div>

        <div className="space-y-3">
          {field ? (
            <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
              <FlowFieldCanvas field={field} colorBy={colorBy} showStreamlines={showStreamlines} />
              <div className="mt-2 text-xs text-neutral-500">
                alpha = {field.alpha.toFixed(2)}&deg;, V&#8734; = {field.Vinf.toFixed(3)}: {field.note}
              </div>
            </div>
          ): (
            <div className="text-sm text-neutral-500 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-lg p-8 text-center">
              {loading ? `Solving... (${elapsedS.toFixed(0)}s elapsed)`: "Run a solve to see the flow field."}
            </div>
          )}

          {re !== "" && <BoundaryLayerPanel loading={blLoading} error={blError} result={blResult} />}
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Viscous half of the coupled solve: theta/delta*/cf/Hk distributions and the
// transition location, from the SAME /api/analyze call this page already
// makes when a Reynolds number is given. Reuses BLChart (Analyze page) so the
// two pages read the boundary layer the same way.
// --------------------------------------------------------------------------- //

function BoundaryLayerPanel({
  loading,
  error,
  result,
}: {
  loading: boolean;
  error: string | null;
  result: AnalyzeResponse | null;
}) {
  if (loading && !result) {
    return (
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3 text-sm text-neutral-500">
        Running the coupled viscous solve...
      </div>
    );
  }
  if (error) return <ErrorBox message={`Boundary-layer solve failed: ${error}`} />;
  if (!result?.bl) return null;

  const tx = result.bl.transition_x;

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
      <h2 className="text-sm font-medium mb-1">Boundary layer (viscous half of the coupled solve)</h2>
      <p className="text-xs text-neutral-500 mb-2">
        The field above is inviscid; this is the viscous half of the same solve at Re ={" "}
        {result.Re != null ? result.Re.toExponential(2) : "?"}, coupled to it through the
        displacement thickness. cl = {result.cl.toFixed(4)}, cd = {result.cd.toFixed(5)} (cdf ={" "}
        {result.cdf != null ? result.cdf.toFixed(5) : ","}, cdp ={" "}
        {result.cdp != null ? result.cdp.toFixed(5) : ","}).
      </p>
      {tx && (
        <p className="text-xs text-neutral-500 mb-2">
          transition (e^n): upper x/c = {tx.upper.toFixed(3)}, lower x/c = {tx.lower.toFixed(3)}{" "}
          (marked as dashed vertical lines below).
        </p>
      )}
      <BLChart bl={result.bl} />
      {result.bl_offset && (
        <div className="mt-3">
          <div className="text-xs font-medium mb-1">
            Displacement-thickness offset (the coupling term the inviscid edge condition sees)
          </div>
          <AirfoilShape coords={result.coords} blOffset={result.bl_offset} height={140} />
        </div>
      )}
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm";

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
      {message}
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
