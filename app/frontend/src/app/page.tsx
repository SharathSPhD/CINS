"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { showcase, type ShowcaseResponse } from "@/lib/api";

interface Gate {
  id: string;
  title: string;
  status: string;
  date: string | null;
  evidence: string;
  commit: string | null;
}

const REPO_URL = "https://github.com/SharathSPhD/CINS";

export default function Home() {
  const [data, setData] = useState<ShowcaseResponse | null>(null);

  useEffect(() => {
    showcase()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  const gates = (data?.gates?.gates as Gate[] | undefined) ?? [];
  const closed = gates.filter((g) => g.status === "closed").length;

  return (
    <div className="mx-auto max-w-4xl px-4 py-16">
      {/* Hero */}
      <h1 className="text-3xl font-semibold tracking-tight">CINS</h1>
      <p className="mt-2 text-neutral-600 dark:text-neutral-400">
        CST Inverse Newton Solver: a deterministic monolithic inverse airfoil design engine.
      </p>
      <p className="mt-4 text-sm text-neutral-600 dark:text-neutral-400">
        Every public airfoil tool (foil.tools, airfoilx.com, Webfoil, NeuralFoil, airfoiltools.com)
        does forward analysis, optimization, or ML surrogates. None solves the inverse problem
        directly: draw a target pressure distribution, get geometry back from a square Newton
        root-find: no outer optimizer, no surrogate, no training data. Appending CST coefficients
        to mfoil&apos;s global Newton system turns inverse airfoil design into a determined
        root-find, and the <strong>Inverse Design Theater</strong> below watches it happen: geometry, pressure, and residuals evolving iteration by iteration, live.
      </p>

      <div className="mt-6 flex flex-wrap gap-3">
        <Link
          href="/inverse"
          className="rounded-lg bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 px-5 py-3 text-sm font-medium hover:opacity-90 transition-opacity"
        >
          Open the Inverse Design Theater &rarr;
        </Link>
        <Link
          href="/gallery"
          className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-5 py-3 text-sm font-medium hover:border-neutral-500 dark:hover:border-neutral-500 transition-colors"
        >
          Browse archived results
        </Link>
      </div>

      {/* Demo video. Rendered from a real solve, not a mock. */}
      <section className="mt-10">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500 mb-2">
          Watch the solver run
        </h2>
        <video
          className="w-full rounded-lg border border-neutral-200 dark:border-neutral-800"
          controls
          preload="none"
          poster="/demo/poster.jpg"
        >
          <source src="/demo/cins-demo-wide.mp4" type="video/mp4" />
          Your browser does not support embedded video. The file is at
          /demo/cins-demo-wide.mp4.
        </video>
        <p className="mt-2 text-xs text-neutral-500">
          A target pressure distribution goes in and a geometry comes back. Every frame of
          the solver sequence is recorded from a real run that converged in five Newton
          iterations to a coefficient error of 2.12e-11.
        </p>
      </section>

      {/* Gate board strip */}
      {gates.length > 0 && (
        <div className="mt-10">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Gate board: {closed}/{gates.length} closed
            </h2>
            <span className="text-xs text-neutral-400">updated {String(data?.gates?.updated ?? "")}</span>
          </div>
          <div className="flex gap-1.5 overflow-x-auto pb-2">
            {gates.map((g) => (
              <div
                key={g.id}
                title={g.evidence}
                className={`shrink-0 rounded-md border px-2.5 py-1.5 text-xs ${
                  g.status === "closed"
                    ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400"
                   : "border-neutral-300 dark:border-neutral-700 text-neutral-500"
                }`}
              >
                <div className="font-mono font-semibold">{g.id}</div>
                <div className="max-w-[9rem] truncate">{g.title}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Nav cards */}
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <Link
          href="/analyze"
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 hover:border-neutral-400 dark:hover:border-neutral-600 transition-colors"
        >
          <div className="font-medium">Analyze</div>
          <div className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Direct mfoil solve, CST Studio coefficient sliders, and boundary-layer distributions.
          </div>
        </Link>
        <Link
          href="/inverse"
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 hover:border-neutral-400 dark:hover:border-neutral-600 transition-colors"
        >
          <div className="font-medium">Inverse Design Theater</div>
          <div className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Monolithic CST-Newton inverse solve, animated live, iteration by iteration.
          </div>
        </Link>
        <Link
          href="/flowfield"
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 hover:border-neutral-400 dark:hover:border-neutral-600 transition-colors"
        >
          <div className="font-medium">Flow Field</div>
          <div className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            |V| / Cp heatmap with client-side streamline tracing, for any airfoil.
          </div>
        </Link>
        <Link
          href="/gallery"
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 hover:border-neutral-400 dark:hover:border-neutral-600 transition-colors"
        >
          <div className="font-medium">Results Gallery</div>
          <div className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Archived T7 recovery run, the T8 NACA panel sweep, and paper figures.
          </div>
        </Link>
      </div>

      <div className="mt-10 flex flex-wrap gap-4 text-sm text-neutral-500">
        <a href={REPO_URL} target="_blank" rel="noreferrer" className="hover:text-neutral-700 dark:hover:text-neutral-300 underline underline-offset-2">
          Repository
        </a>
        <a href={`${REPO_URL}/tree/main/paper`} target="_blank" rel="noreferrer" className="hover:text-neutral-700 dark:hover:text-neutral-300 underline underline-offset-2">
          Paper (P1, AIAA)
        </a>
        <a href="https://sharathsphd.github.io/CINS/" target="_blank" rel="noreferrer" className="hover:text-neutral-700 dark:hover:text-neutral-300 underline underline-offset-2">
          Progress site (GitHub Pages)
        </a>
      </div>
    </div>
  );
}
