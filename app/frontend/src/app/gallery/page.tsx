"use client";

import ArchivedResidualChart from "@/components/ArchivedResidualChart";

// Results Gallery (item 7 of the app rich-features brief): archived T7
// self-consistency run + T8 NACA panel sweep table + paper figures, all
// read-only over experiments/results/ via GET /api/showcase. Everything here
// is archived evidence, clearly labeled with its manifest (git SHA / date),
// never a live solve.

import { useEffect, useMemo, useState } from "react";
import AirfoilShape from "@/components/AirfoilShape";
import CstBasisFigure from "@/components/CstBasisFigure";
import CstPanel from "@/components/CstPanel";
import { describeError, showcase, type ShowcaseResponse } from "@/lib/api";
import { loadCorpus, type CorpusAirfoil } from "@/lib/corpus";

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
        {data.manifest_note}. Everything on this page is stored output, so nothing here waits
        on a solve. Use Analyze, Inverse or Flow Field to run the solver yourself.
      </p>
      <section className="mt-8">
        <h2 className="text-lg font-medium">Flow field showcase</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          Inviscid velocity and pressure fields across a spread of camber, thickness and angle
          of attack. These are stored renders, so this page never waits on a solve. Open{" "}
          <a href="/flowfield" className="underline underline-offset-2">Flow Field</a> to drive
          any of the 123 UIUC sections or a NACA code yourself.
        </p>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {[
            ["naca2412_a6", "NACA 2412, alpha 6°, Cp"],
            ["naca0012_a10", "NACA 0012, alpha 10°, |V|"],
            ["e212_a4", "Eppler 212, alpha 4°, Cp"],
            ["clarkk_a4", "Clark-K, alpha 4°, |V|"],
          ].map(([file, label]) => (
            <figure key={file} className="rounded-lg border border-neutral-200 dark:border-neutral-800 overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element -- static render served by the backend */}
              <img src={`/static/figures/flowfield/${file}.png`} alt={label} className="w-full h-auto" />
              <figcaption className="px-2 py-1 text-xs text-neutral-500">{label}</figcaption>
            </figure>
          ))}
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
          Each section run through the monolithic CST-Newton inverse solve, one row per
          section.
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

// Airfoil corpus grid: reads /corpus.json (public/corpus.json, generated by
// scripts/gen_corpus.py) directly, one fetch for all 143 sections, cached in
// module state by src/lib/corpus.ts. Every card draws its true outline
// (equal x/y scale, full chord, both surfaces, thin-card aspect) and its
// order-8 CST fit is already in hand, so selecting a card shows what the
// CST parameterization made of it with no further network round trip.
function AirfoilCorpusSection() {
  const [corpus, setCorpus] = useState<CorpusAirfoil[] | null>(null);
  const [corpusError, setCorpusError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [visible, setVisible] = useState(24);
  // Defaults to NACA 2412 (the same section paper_figures_theory.py's
  // fig_cst_basis uses) once the corpus loads, so the "how a shape is built"
  // panel is visible on first paint rather than hidden behind a click.
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    loadCorpus()
      .then((c) => {
        setCorpus(c.airfoils);
        setSelectedId((prev) => prev ?? (c.airfoils.some((a) => a.id === "naca:2412") ? "naca:2412" : (c.airfoils[0]?.id ?? null)));
      })
      .catch((err) => setCorpusError(describeError(err)));
  }, []);

  const filtered = useMemo(
    () => (corpus ?? []).filter((a) => a.name.toLowerCase().includes(q.toLowerCase())),
    [corpus, q],
  );

  const nNaca = corpus?.filter((a) => a.source === "naca").length ?? 0;
  const nUiuc = corpus?.filter((a) => a.source === "uiuc").length ?? 0;
  const selected = corpus?.find((a) => a.id === selectedId) ?? null;

  return (
    <section className="mt-8">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-medium">Airfoil corpus</h2>
        <div className="text-sm text-neutral-600 dark:text-neutral-400">
          {corpus ? `${corpus.length} airfoils (${nNaca} NACA presets + ${nUiuc} UIUC sections)` : "loading..."}
        </div>
      </div>
      <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
        Every section&apos;s outline and order-8 CST fit, read from one static asset. Select a card
        to see what the CST parameterization made of it, panel by panel: the class function, the
        Bernstein shape functions, the coefficient-weighted terms, and the surface they sum to.
      </p>
      {corpusError && (
        <div className="mt-2 rounded-md border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
          {corpusError}
        </div>
      )}
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
          <AirfoilThumb key={a.id} item={a} selected={a.id === selectedId} onSelect={() => setSelectedId(a.id === selectedId ? null : a.id)} />
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

      {selected && (
        <div className="mt-4 space-y-4">
          <CstPanel
            title={`CST parameterization: ${selected.name}`}
            primary={{
              label: selected.name,
              A_upper: selected.A_upper,
              A_lower: selected.A_lower,
              fitRms: selected.fit_rms,
            }}
          />
          <CstBasisFigure
            name={selected.name}
            A_upper={selected.A_upper}
            A_lower={selected.A_lower}
            // corpus.json (scripts/gen_corpus.py) doesn't carry zeta_T
            // separately, but the decimated coordinate list keeps its true
            // TE endpoints at both ends (decimate() always includes index 0
            // and N-1), so the real trailing-edge offsets are read straight
            // off the source outline rather than assumed to be zero. Node
            // ordering follows mfoil (src/cins/CLAUDE.md): TE-lower -> LE ->
            // TE-upper, so index 0 is the lower TE point and the last index
            // is the upper TE point.
            zetaTUpper={selected.coords[selected.coords.length - 1]?.[1] ?? 0}
            zetaTLower={selected.coords[0]?.[1] ?? 0}
            sourceCoords={selected.coords}
            fitRms={selected.fit_rms}
          />
        </div>
      )}
    </section>
  );
}

function AirfoilThumb({
  item,
  selected,
  onSelect,
}: {
  item: CorpusAirfoil;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`text-left rounded-lg border px-2 py-1.5 ${
        selected
          ? "border-neutral-900 dark:border-neutral-100"
          : "border-neutral-200 dark:border-neutral-800 hover:border-neutral-400 dark:hover:border-neutral-600"
      }`}
    >
      <div className="font-mono text-xs truncate">{item.name}</div>
      <AirfoilShape coords={item.coords} width={240} height={80} margin={6} showTicks={false} />
      <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-neutral-500">
        <span>
          t/c {(item.thickness * 100).toFixed(1)}% @ {item.thickness_x.toFixed(2)}c
        </span>
        <span>
          camber {(item.camber * 100).toFixed(1)}% @ {item.camber_x.toFixed(2)}c
        </span>
      </div>
    </button>
  );
}


