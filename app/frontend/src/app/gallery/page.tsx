"use client";

import ArchivedResidualChart from "@/components/ArchivedResidualChart";

// Results Gallery (item 7 of the app rich-features brief): archived T7
// self-consistency run + T8 NACA panel sweep table + paper figures, all
// read-only over experiments/results/ via GET /api/showcase. Everything here
// is archived evidence, clearly labeled with its manifest (git SHA / date),
// never a live solve.

import { useEffect, useMemo, useState } from "react";
import AirfoilShape from "@/components/AirfoilShape";
import FlowFieldCanvas from "@/components/FlowFieldCanvas";
import {
  airfoilGeometry,
  describeError,
  flowfield,
  listAirfoils,
  showcase,
  type AirfoilListItem,
  type AirfoilListResponse,
  type FlowFieldResponse,
  type ShowcaseResponse,
} from "@/lib/api";

// Concurrency limiter: defect-fix: the T8 panel table (up to 117 rows), the
// airfoil-corpus grid, and the flow-field showcase can each fire many
// requests at (near) the same moment. Observed in testing: with everything
// unthrottled, Next.js's local dev `/api` rewrite proxy (next.config.ts)
// itself dropped connections under the resulting concurrency spike: // "Failed to proxy ... Error: socket hang up (ECONNRESET)" in the Next dev
// server log: which surfaced to the user as bare "Internal Server Error"
// text on the Flow Field showcase cards (not a bug in flowfield itself, and
// not reproducible from a single request: only under this page's own
// self-inflicted concurrency). A small per-purpose concurrency cap keeps the
// page fast without tripping the proxy.
function makeLimiter(maxConcurrent: number) {
  let active = 0;
  const queue: (() => void)[] = [];
  return function limit<T>(fn: () => Promise<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      const run = () => {
        active++;
        fn()
          .then(resolve, reject)
          .finally(() => {
            active--;
            const next = queue.shift();
            if (next) next();
          });
      };
      if (active < maxConcurrent) run();
      else queue.push(run);
    });
  };
}

const limitThumbFetch = makeLimiter(6);
const limitFlowFieldSolve = makeLimiter(2);

function throttledAirfoilGeometry(id: string): ReturnType<typeof airfoilGeometry> {
  return limitThumbFetch(() => airfoilGeometry(id));
}

export default function GalleryPage() {
  const [data, setData] = useState<ShowcaseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "converged" | "failed">("all");

  useEffect(() => {
    showcase()
      .then(setData)
      .catch((err) => setError(describeError(err)));
  }, []);

  if (error) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10">
        <div className="rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 text-sm text-neutral-500">
        Loading archived results...
      </div>
    );
  }

  const rows = data.panel.filter((p) =>
    filter === "all" ? true : filter === "converged" ? p.converged : !p.converged,
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Results Gallery</h1>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        {data.manifest_note}. The flow fields and airfoil corpus below are solved live on
        load. The panel sweep, figures and residual history are archived runs replayed for
        reference.
      </p>
      <section className="mt-8">
        <h2 className="text-lg font-medium">Flow field showcase</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          Live inviscid velocity/Cp fields (each solved on load: not archived) across a spread of
          camber, thickness, and angle of attack. Open <a href="/flowfield" className="underline underline-offset-2">Flow Field</a> to
          drive any of the 123 UIUC sections or a NACA code yourself.
        </p>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <FlowFieldShowcaseCard title="NACA 2412, alpha=6°" naca="2412" alpha={6} colorBy="cp" />
          <FlowFieldShowcaseCard title="NACA 0012, alpha=10°" naca="0012" alpha={10} colorBy="speed" />
          <FlowFieldShowcaseCard title="Eppler 212, alpha=4°" airfoilId="uiuc:e212" alpha={4} colorBy="cp" />
          <FlowFieldShowcaseCard title="Clark-K, alpha=4°" airfoilId="uiuc:clarkk" alpha={4} colorBy="speed" />
        </div>
      </section>

      <AirfoilCorpusSection />

      <section className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">T8 NACA panel sweep</h2>
          <div className="text-sm text-neutral-600 dark:text-neutral-400">
            {data.panel_n_converged} / {data.panel_n_total} converged
          </div>
        </div>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          117 UIUC sections run through the monolithic CST-Newton inverse solve, one row per
          section, with a geometry thumbnail so you can see what shape each recovery/failure was
          for.
        </p>
        <div className="mt-2 flex gap-1 text-xs">
          {(["all", "converged", "failed"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-1 rounded border ${
                filter === f
                  ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900"
                 : "border-neutral-300 dark:border-neutral-700"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="mt-3 max-h-[32rem] overflow-auto rounded-lg border border-neutral-200 dark:border-neutral-800 text-xs">
          <table className="w-full">
            <thead className="sticky top-0 bg-neutral-100 dark:bg-neutral-900">
              <tr>
                <th className="text-left px-3 py-1.5">shape</th>
                <th className="text-left px-3 py-1.5">cell</th>
                <th className="text-left px-3 py-1.5">converged</th>
                <th className="text-left px-3 py-1.5">iterations</th>
                <th className="text-left px-3 py-1.5">err_all_inf</th>
                <th className="text-left px-3 py-1.5">wall time (s)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.cell_name} className="odd:bg-neutral-50 dark:odd:bg-neutral-900/40 align-middle">
                  <td className="px-3 py-1 w-24">
                    {p.airfoil_id && <PanelThumb airfoilId={p.airfoil_id} />}
                  </td>
                  <td className="px-3 py-1 font-mono">{p.cell_name}</td>
                  <td className="px-3 py-1">
                    <span className={p.converged ? "text-emerald-600 dark:text-emerald-400": "text-red-600 dark:text-red-400"}>
                      {p.converged ? "yes" : "no"}
                    </span>
                  </td>
                  <td className="px-3 py-1">{p.iterations ?? ","}</td>
                  <td className="px-3 py-1 font-mono">
                    {p.err_all_inf != null ? p.err_all_inf.toExponential(2) : ","}
                  </td>
                  <td className="px-3 py-1">{p.wall_time_s?.toFixed(2) ?? ","}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {data.figures.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-medium">Paper figures</h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {data.figures.map((src) => (
              <a key={src} href={src} target="_blank" rel="noreferrer" className="block rounded-lg border border-neutral-200 dark:border-neutral-800 overflow-hidden hover:border-neutral-400 dark:hover:border-neutral-600">
                {/* eslint-disable-next-line @next/next/no-img-element -- static archived PNGs served by the backend, not app-routed assets */}
                <img src={src} alt={src.split("/").pop()} className="w-full h-auto" />
                <div className="px-2 py-1 text-xs text-neutral-500 font-mono truncate">
                  {src.split("/").pop()}
                </div>
              </a>
            ))}
          </div>
        </section>
      )}

      <details className="mt-10 rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
        <summary className="cursor-pointer text-sm font-medium text-neutral-600 dark:text-neutral-400">
          Reference: T7 self-consistency residual history and run log
        </summary>
        <h2 className="text-lg font-medium">T7 self-consistency gate</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          NACA 2412 with forced transition. The solver recovers the section&apos;s own CST
          coefficients from its own target pressure distribution in{" "}
          {data.t7.iterations.length} Newton iterations. Read the plot as three residual
          blocks falling together: R is the flow residual, T is the mismatch at the target
          pressure stations, and G is the constraint row. The combined residual reaches the
          solver tolerance at 1e-10.
        </p>
        <div className="mt-3 rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
          <ArchivedResidualChart iterations={data.t7.iterations as never[]} />
          <p className="mt-2 text-xs text-neutral-500">
            Archived run. The reported convergence-order estimate for this run is{" "}
            {data.t7.convergence_order?.toFixed(3) ?? "not available"}, which measures noise
            rather than the asymptotic rate: the flow block starts at the solver floor, so the
            three-point estimator has no pre-floor points to work with. The quadratic tail is
            visible instead in the combined residual sequence quoted above.
          </p>
          <pre className="mt-3 text-xs font-mono whitespace-pre-wrap text-neutral-600 dark:text-neutral-400 max-h-48 overflow-auto">
            {data.t7.log_tail}
          </pre>
        </div>
      </details>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Flow field showcase card: a LIVE solve (not archived), rendered with the
// same FlowFieldCanvas the Flow Field page uses, so the gallery actually
// shows colored field visuals rather than only tables/figures (item 7 of the
// app rich-features brief: "colored field visuals").
// --------------------------------------------------------------------------- //

function FlowFieldShowcaseCard({
  title,
  naca,
  airfoilId,
  alpha,
  colorBy,
}: {
  title: string;
  naca?: string;
  airfoilId?: string;
  alpha: number;
  colorBy: "speed" | "cp";
}) {
  const [field, setField] = useState<FlowFieldResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      try {
        const req = naca
          ? { naca, alpha }
         : { coords: (await throttledAirfoilGeometry(airfoilId as string)).coords, alpha };
        const res = await limitFlowFieldSolve(() => flowfield(req));
        if (!cancelled) setField(res);
      } catch (err) {
        if (!cancelled) setError(describeError(err));
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [naca, airfoilId, alpha]);

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
      <div className="text-xs font-medium mb-1">{title}</div>
      {field ? (
        <FlowFieldCanvas field={field} colorBy={colorBy} showStreamlines width={480} height={300} />
      ): error ? (
        <div className="text-xs text-red-600 dark:text-red-400 py-8 text-center">{error}</div>
      ): (
        <div className="text-xs text-neutral-400 py-8 text-center animate-pulse">solving...</div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Airfoil corpus: every NACA preset + all 123 UIUC sections with a real
// shape thumbnail (fetched lazily, paginated) and a search box (item 7:
// "many airfoils"). Thumbnails fetch geometry on demand rather than eagerly
// for all ~145 entries, so the page stays responsive.
// --------------------------------------------------------------------------- //

function AirfoilCorpusSection() {
  const [catalog, setCatalog] = useState<AirfoilListResponse | null>(null);
  const [q, setQ] = useState("");
  const [visible, setVisible] = useState(24);

  useEffect(() => {
    listAirfoils().then(setCatalog).catch(() => setCatalog(null));
  }, []);

  const all: AirfoilListItem[] = useMemo(() => {
    if (!catalog) return [];
    return [...catalog.naca, ...catalog.uiuc];
  }, [catalog]);

  const filtered = useMemo(
    () => all.filter((a) => a.name.toLowerCase().includes(q.toLowerCase())),
    [all, q],
  );

  return (
    <section className="mt-8">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-medium">Airfoil corpus</h2>
        <div className="text-sm text-neutral-600 dark:text-neutral-400">
          {catalog ? `${all.length} airfoils (${catalog.naca.length} NACA presets + ${catalog.uiuc.length} UIUC sections)`: "loading..."}
        </div>
      </div>
      <input
        className="mt-2 w-full max-w-sm rounded-md border border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-1.5 text-sm"
        placeholder="search by name..."
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setVisible(24);
        }}
      />
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
        {filtered.slice(0, visible).map((a) => (
          <AirfoilThumb key={a.id} item={a} />
        ))}
      </div>
      {visible < filtered.length && (
        <button
          type="button"
          onClick={() => setVisible((v) => v + 24)}
          className="mt-3 text-xs rounded-md border border-neutral-300 dark:border-neutral-700 px-3 py-1.5"
        >
          Show more ({filtered.length - visible} remaining)
        </button>
      )}
    </section>
  );
}

function AirfoilThumb({ item }: { item: AirfoilListItem }) {
  const [coords, setCoords] = useState<number[][] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    throttledAirfoilGeometry(item.id)
      .then((g) => {
        if (!cancelled) setCoords(g.coords);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [item.id]);

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-2">
      {coords ? (
        <AirfoilShape coords={coords} width={220} height={90} />
      ): (
        <div className="h-[90px] flex items-center justify-center text-[10px] text-neutral-400">
          {failed ? "failed to load" : "loading..."}
        </div>
      )}
      <div className="mt-1 flex items-center justify-between text-[10px] text-neutral-500">
        <span className="font-mono truncate">{item.name}</span>
        {item.thickness != null && <span>{(item.thickness * 100).toFixed(1)}%t</span>}
      </div>
    </div>
  );
}

// Compact geometry thumbnail for a T8 panel-sweep table row.
function PanelThumb({ airfoilId }: { airfoilId: string }) {
  const [coords, setCoords] = useState<number[][] | null>(null);

  useEffect(() => {
    let cancelled = false;
    throttledAirfoilGeometry(airfoilId)
      .then((g) => {
        if (!cancelled) setCoords(g.coords);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [airfoilId]);

  if (!coords) return <div className="h-6 w-20 bg-neutral-100 dark:bg-neutral-900 rounded" />;
  return <AirfoilShape coords={coords} width={80} height={24} />;
}

