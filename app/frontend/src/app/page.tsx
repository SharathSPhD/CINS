import Link from "next/link";

export default function Home() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">CINS</h1>
      <p className="mt-2 text-neutral-600 dark:text-neutral-400">
        CST Inverse Newton Solver — a deterministic monolithic inverse airfoil design engine.
      </p>
      <p className="mt-4 text-sm text-neutral-600 dark:text-neutral-400">
        Every public airfoil tool (foil.tools, airfoilx.com, Webfoil, NeuralFoil, airfoiltools.com)
        does forward analysis, optimization, or ML surrogates. None solves the inverse problem
        directly: draw a target pressure distribution, get geometry back from a square Newton
        root-find — no outer optimizer, no surrogate, no training data.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <Link
          href="/analyze"
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 hover:border-neutral-400 dark:hover:border-neutral-600 transition-colors"
        >
          <div className="font-medium">Analyze</div>
          <div className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Direct mfoil solve on a NACA airfoil: Cp, cl, cd, cm.
          </div>
        </Link>
        <Link
          href="/inverse"
          className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-4 hover:border-neutral-400 dark:hover:border-neutral-600 transition-colors"
        >
          <div className="font-medium">Inverse</div>
          <div className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Monolithic CST-Newton inverse solve, with live convergence tracking.
          </div>
        </Link>
      </div>
    </div>
  );
}
